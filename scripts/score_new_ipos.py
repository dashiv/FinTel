"""
PHASE 5 — STEP 3: SCORE NEW IPO FILINGS
=========================================
Fetches recent unscored filings from fintel.db,
builds features, runs model_scorer, writes scores back.

This is what makes the dashboard show AI-scored signals.

Run:  python scripts/score_new_ipos.py
Auto: APScheduler calls this daily via dashboard scheduler
"""

import os, sys, sqlite3, time
import pandas as pd
from datetime import datetime, timedelta
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn
from loguru import logger

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.model_scorer import score_company, get_available_regimes
from utils.events_db import init_events_db, get_regime, get_tech_cycle

console = Console()

ROOT      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINTEL_DB = os.path.join(ROOT, "fintel.db")          # live dashboard DB
HIST_DB   = os.path.join(ROOT, "fintel_historical.db")


# ── DB HELPERS ────────────────────────────────────────────────────────────────

def ensure_score_columns():
    """
    Add scoring columns to ipo_filings if they don't exist yet.
    Safe to call repeatedly — uses ALTER TABLE IF NOT EXISTS pattern.
    """
    conn = sqlite3.connect(FINTEL_DB)
    c    = conn.cursor()

    new_cols = [
        ("fintel_score",      "REAL"),
        ("verdict",           "TEXT"),
        ("regime",            "TEXT"),
        ("tech_cycle",        "TEXT"),
        ("beat_spy_prob",     "REAL"),
        ("expected_return",   "REAL"),
        ("winner_prob",       "REAL"),
        ("model_confidence",  "TEXT"),
        ("model_used",        "TEXT"),
        ("fallback_used",     "INTEGER"),
        ("scored_at",         "TEXT"),
    ]

    existing = [row[1] for row in c.execute("PRAGMA table_info(ipo_filings)").fetchall()]

    for col_name, col_type in new_cols:
        if col_name not in existing:
            c.execute(f"ALTER TABLE ipo_filings ADD COLUMN {col_name} {col_type}")
            logger.info(f"Added column: {col_name}")

    conn.commit()
    conn.close()


def get_unscored_filings(days_back: int = 90, force_rescore: bool = False) -> list[dict]:
    """
    Returns filings that haven't been scored yet (or all, if force_rescore).
    """
    conn  = sqlite3.connect(FINTEL_DB)
    since = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    if force_rescore:
        query = "SELECT * FROM ipo_filings WHERE filing_date >= ?"
    else:
        query = """
            SELECT * FROM ipo_filings
            WHERE filing_date >= ?
              AND (fintel_score IS NULL OR scored_at IS NULL)
        """

    rows = conn.execute(query, (since,)).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM ipo_filings LIMIT 0").description]
    conn.close()
    return [dict(zip(cols, row)) for row in rows]


def get_ipo_market_temp(filing_date: str) -> int:
    """Count filings in fintel.db in the 90 days before this date."""
    if not filing_date:
        return 0
    try:
        conn  = sqlite3.connect(FINTEL_DB)
        d     = filing_date[:10]
        d90   = (datetime.strptime(d, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")
        count = conn.execute("""
            SELECT COUNT(*) FROM ipo_filings
            WHERE filing_date >= ? AND filing_date < ?
        """, (d90, d)).fetchone()[0]
        conn.close()
        return int(count)
    except Exception:
        return 0


def enrich_with_hist_data(filing: dict) -> dict:
    """
    Pull early return data (30d, 60d, 90d) from fintel_historical.db
    if this company has a ticker and historical data. Enriches features.
    """
    if not os.path.exists(HIST_DB):
        return filing

    ticker = filing.get("ticker", "")
    if not ticker:
        return filing

    try:
        conn = sqlite3.connect(HIST_DB)
        rows = conn.execute("""
            SELECT pc.days_offset, pc.return_vs_ipo
            FROM price_checkpoints pc
            JOIN historical_ipos hi ON pc.company_id = hi.id
            WHERE hi.ticker = ?
              AND pc.days_offset IN (30, 60, 90, 180)
        """, (ticker,)).fetchall()
        conn.close()

        for days_offset, ret in rows:
            filing[f"return_{int(days_offset)}d"] = ret
    except Exception:
        pass

    return filing


def save_score(filing_id: int, score_result: dict):
    """Write scored result back to ipo_filings."""
    conn = sqlite3.connect(FINTEL_DB)
    conn.execute("""
        UPDATE ipo_filings SET
            fintel_score     = ?,
            verdict          = ?,
            regime           = ?,
            tech_cycle       = ?,
            beat_spy_prob    = ?,
            expected_return  = ?,
            winner_prob      = ?,
            model_confidence = ?,
            model_used       = ?,
            fallback_used    = ?,
            scored_at        = ?
        WHERE id = ?
    """, (
        score_result.get("fintel_score"),
        score_result.get("verdict"),
        score_result.get("regime"),
        score_result.get("tech_cycle"),
        score_result.get("beat_spy_prob"),
        score_result.get("expected_return"),
        score_result.get("winner_prob"),
        score_result.get("confidence"),
        score_result.get("model_used"),
        1 if score_result.get("fallback_used") else 0,
        score_result.get("scored_at"),
        filing_id,
    ))
    conn.commit()
    conn.close()


# ── SUMMARY REPORT ────────────────────────────────────────────────────────────

def print_score_summary(results: list[dict]):
    if not results:
        return

    df = pd.DataFrame(results)
    df = df[df["fintel_score"].notna()]

    if df.empty:
        console.print("[yellow]No scores computed.[/yellow]")
        return

    verdicts = df["verdict"].value_counts().to_dict()

    t = Table(title="📊 Scoring Summary", header_style="bold cyan", show_lines=True)
    t.add_column("Metric",        style="dim",   width=30)
    t.add_column("Value",         justify="right", style="bold", width=15)

    t.add_row("Companies scored",    str(len(df)))
    t.add_row("Avg FinTel Score",    f"{df['fintel_score'].mean():.1f}")
    t.add_row("🟢 Strong Buy (≥75)", str(verdicts.get("strong_buy", 0)))
    t.add_row("🟡 Watch (60–74)",    str(verdicts.get("watch", 0)))
    t.add_row("⚪ Neutral (45–59)",  str(verdicts.get("neutral", 0)))
    t.add_row("🔴 Avoid (<45)",      str(verdicts.get("avoid", 0)))

    if "beat_spy_prob" in df.columns and df["beat_spy_prob"].notna().any():
        t.add_row("Avg Beat-SPY Prob",  f"{df['beat_spy_prob'].mean():.1f}%")
    if "expected_return" in df.columns and df["expected_return"].notna().any():
        t.add_row("Avg Expected Return", f"{df['expected_return'].mean():+.1f}%")

    console.print("\n")
    console.print(t)

    # Top picks
    top = df.nlargest(5, "fintel_score")[
        ["company_name", "fintel_score", "verdict",
         "regime", "beat_spy_prob", "expected_return"]
    ] if "company_name" in df.columns else df.nlargest(5, "fintel_score")

    console.print("\n[bold green]🎯 Top 5 Signals:[/bold green]")
    t2 = Table(header_style="bold green", show_lines=False)
    for col in top.columns:
        t2.add_column(str(col), style="dim")
    for _, row in top.iterrows():
        t2.add_row(*[str(v) if v is not None else "—" for v in row.values])
    console.print(t2)


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main(days_back: int = 90, force_rescore: bool = False):
    console.rule("[bold magenta]🎯 FinTel — Scoring New IPO Filings[/bold magenta]")

    # ── Step 0: Verify events DB
    init_events_db()

    # ── Step 1: Check trained models exist
    available = get_available_regimes()
    if not available:
        console.print(
            "[red]❌ No trained models found.[/red]\n"
            "[dim]Run: python scripts/train_models.py[/dim]"
        )
        return

    console.print(f"[green]✅ Models loaded for regimes:[/green] {available}")

    # ── Step 2: Ensure score columns exist in fintel.db
    ensure_score_columns()

    # ── Step 3: Get unscored filings
    filings = get_unscored_filings(days_back, force_rescore)
    if not filings:
        console.print(
            f"[green]✅ All filings already scored.[/green]\n"
            f"[dim]Use --force to rescore. Run scout to find new filings.[/dim]"
        )
        return

    console.print(f"[bold]{len(filings)}[/bold] filings to score\n")

    results = []

    with Progress(
        SpinnerColumn(), TextColumn("{task.description}"),
        BarColumn(), MofNCompleteColumn()
    ) as prog:
        task = prog.add_task("Scoring...", total=len(filings))

        for filing in filings:
            fid  = filing.get("id")
            name = filing.get("company_name", "Unknown")

            # Enrich with market temperature + historical data
            filing["ipo_market_temp_90d"] = get_ipo_market_temp(filing.get("filing_date",""))
            filing = enrich_with_hist_data(filing)

            try:
                result           = score_company(filing)
                result["id"]     = fid
                result["company_name"] = name

                if result.get("fintel_score") is not None:
                    save_score(fid, result)
                    results.append(result)

            except Exception as e:
                logger.warning(f"Score failed for {name} (id={fid}): {e}")

            prog.advance(task)
            time.sleep(0.01)

    print_score_summary(results)

    console.print(f"\n[dim]Scores saved to: {FINTEL_DB}[/dim]")
    console.print("[dim]Refresh dashboard to see updated signals.[/dim]")
    console.print("[dim]Next: python scripts/backtest.py[/dim]")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Score recent IPO filings")
    parser.add_argument("--days",   type=int,  default=90,    help="Days back to score")
    parser.add_argument("--force",  action="store_true",       help="Rescore already-scored filings")
    args = parser.parse_args()
    main(days_back=args.days, force_rescore=args.force)
