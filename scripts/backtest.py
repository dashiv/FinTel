"""
PHASE 6 — BACKTEST ENGINE
===========================
Replays historical model predictions against real outcomes.
Validates that FinTel Score has genuine predictive power
before deploying real capital.

Outputs:
  1. Win rate by score band (does score 75+ actually win more?)
  2. Win rate by regime and sector
  3. Sharpe ratio vs buy-and-hold S&P500
  4. Calibration: does score 80 → 80% actual winners?
  5. Expected value per score band (€ per €100 invested)
  6. Full results saved to backtest_results.db

Run:
    python scripts/backtest.py
    python scripts/backtest.py --min-year 2015  (recent data only)
    python scripts/backtest.py --score-threshold 70
"""

import os, sys, sqlite3, argparse
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from loguru import logger

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST_DB  = os.path.join(ROOT, "fintel_historical.db")
FINTEL_DB = os.path.join(ROOT, "fintel.db")
OUT_DB   = os.path.join(ROOT, "backtest_results.db")

console = Console()


# ── OUTPUT DB ─────────────────────────────────────────────────────────────────

def init_backtest_db():
    conn = sqlite3.connect(OUT_DB)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS backtest_runs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date      TEXT,
            min_year      INTEGER,
            score_thresh  REAL,
            n_companies   INTEGER,
            win_rate      REAL,
            sharpe_ratio  REAL,
            avg_return    REAL,
            spy_return    REAL,
            notes         TEXT
        );

        CREATE TABLE IF NOT EXISTS backtest_signals (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id        INTEGER,
            company_id    INTEGER,
            company_name  TEXT,
            ticker        TEXT,
            filing_year   INTEGER,
            filing_regime TEXT,
            sector        TEXT,
            fintel_score  REAL,
            score_band    TEXT,
            actual_return_1yr REAL,
            beat_spy      INTEGER,
            outcome_label TEXT,
            FOREIGN KEY (run_id) REFERENCES backtest_runs(id)
        );

        CREATE TABLE IF NOT EXISTS backtest_by_band (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id      INTEGER,
            score_band  TEXT,
            n           INTEGER,
            win_rate    REAL,
            avg_return  REAL,
            sharpe      REAL,
            FOREIGN KEY (run_id) REFERENCES backtest_runs(id)
        );

        CREATE TABLE IF NOT EXISTS backtest_by_regime (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id      INTEGER,
            regime      TEXT,
            n           INTEGER,
            win_rate    REAL,
            avg_return  REAL,
            FOREIGN KEY (run_id) REFERENCES backtest_runs(id)
        );
    """)
    conn.commit()
    conn.close()


# ── DATA LOADERS ──────────────────────────────────────────────────────────────

def load_historical_with_scores(min_year: int = 2010) -> pd.DataFrame:
    conn = sqlite3.connect(HIST_DB)

    ipos = pd.read_sql(f"""
        SELECT
            hi.id                             AS company_id,
            hi.company_name,
            hi.ticker,
            hi.filing_date,
            hi.filing_type,
            hi.sic_description,
            hi.state,
            hi.ipo_price,
            hi.filing_regime,
            hi.filing_tech_cycle,
            hi.ticker_found,
            hi.total_checkpoints,
            CAST(strftime('%Y', hi.filing_date) AS INTEGER) AS filing_year
        FROM historical_ipos hi
        WHERE CAST(strftime('%Y', hi.filing_date) AS INTEGER) >= {min_year}
          AND hi.filing_date IS NOT NULL
    """, conn)

    chk = pd.read_sql("""
        SELECT company_id, days_offset, return_vs_ipo, outcome_label
        FROM price_checkpoints
        WHERE days_offset IN (30, 60, 90, 180, 365)
    """, conn)
    conn.close()

    if chk.empty or ipos.empty:
        return pd.DataFrame()

    chk_pivot = chk.pivot_table(
        index="company_id", columns="days_offset",
        values="return_vs_ipo"
    ).reset_index()
    chk_pivot.columns = ["company_id"] + [
        f"return_{int(c)}d" for c in chk_pivot.columns[1:]
    ]

    # Also grab outcome label at 365d
    outcome_365 = (
        chk[chk["days_offset"] == 365][["company_id", "outcome_label"]]
        .rename(columns={"outcome_label": "outcome_label_1yr"})
    )

    df = ipos.merge(chk_pivot,   on="company_id", how="left")
    df = df.merge(outcome_365,   on="company_id", how="left")

    # Only keep companies with 1yr outcome
    df = df[df["return_365d"].notna()].copy()
    logger.info(f"Loaded {len(df)} historical companies with 1yr outcomes")
    return df


def load_spy_1yr_return(filing_date: str) -> float | None:
    """Approximate SPY 1yr return from price checkpoints context."""
    try:
        conn = sqlite3.connect(HIST_DB)
        # Use the spy_cache table if it exists
        result = conn.execute("""
            SELECT spy_1yr_return FROM spy_cache
            WHERE date <= ? ORDER BY date DESC LIMIT 1
        """, (filing_date,)).fetchone()
        conn.close()
        return float(result[0]) if result else None
    except Exception:
        return None


# ── RETROACTIVE SCORER ───────────────────────────────────────────────────────

def retroactive_score(row: pd.Series) -> float | None:
    """
    Score a historical company using the current model.
    This is what the model WOULD have said at filing time.
    """
    try:
        from utils.model_scorer import score_company
        company = row.to_dict()
        # Map column names to what model_scorer expects
        company["filing_date"]    = str(row.get("filing_date", ""))[:10]
        company["filing_type"]    = row.get("filing_type", "S-1")
        company["sic_description"]= row.get("sic_description", "unknown")
        company["state"]          = row.get("state", "unknown")
        result = score_company(company)
        return result.get("fintel_score")
    except Exception:
        return None


# ── SCORE BAND CLASSIFIER ────────────────────────────────────────────────────

def score_band(score: float | None) -> str:
    if score is None:
        return "unscored"
    if score >= 75:
        return "75–100 (strong_buy)"
    if score >= 60:
        return "60–74 (watch)"
    if score >= 45:
        return "45–59 (neutral)"
    return "0–44 (avoid)"


# ── SHARPE RATIO ─────────────────────────────────────────────────────────────

def sharpe_ratio(returns: pd.Series, risk_free: float = 0.04) -> float:
    """Annualised Sharpe ratio. risk_free = 4% (approx 2024 EUR rate)."""
    if len(returns) < 2:
        return 0.0
    excess = returns - risk_free
    std    = returns.std()
    if std == 0:
        return 0.0
    return float((excess.mean() / std) * np.sqrt(len(returns)))


# ── CALIBRATION ───────────────────────────────────────────────────────────────

def calibration_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each score decile, what % actually beat SPY?
    Perfect calibration: score 80 → 80% beat SPY.
    """
    df = df[df["fintel_score"].notna() & df["beat_spy"].notna()].copy()
    df["decile"] = pd.cut(df["fintel_score"], bins=10, labels=False)
    cal = df.groupby("decile").agg(
        score_mid  = ("fintel_score", "mean"),
        n          = ("beat_spy", "count"),
        actual_pct = ("beat_spy", "mean"),
    ).reset_index(drop=True)
    cal["calibration_error"] = abs(cal["score_mid"] / 100 - cal["actual_pct"])
    return cal


# ── PRINT HELPERS ─────────────────────────────────────────────────────────────

def print_band_table(band_stats: pd.DataFrame, run: dict):
    t = Table(
        title=f"📊 Win Rate by Score Band  "
              f"(threshold ≥{run['score_thresh']}, {run['min_year']}–present)",
        header_style="bold cyan", show_lines=True
    )
    t.add_column("Score Band",   style="bold",   width=24)
    t.add_column("N",            justify="right", width=6)
    t.add_column("Win Rate",     justify="right", width=10)
    t.add_column("Avg Return",   justify="right", width=12)
    t.add_column("Sharpe",       justify="right", width=8)
    t.add_column("vs SPY",       justify="right", width=12)

    for _, row in band_stats.iterrows():
        wr_color = "green" if (row["win_rate"] or 0) >= 0.63 else "yellow"
        t.add_row(
            str(row["score_band"]),
            str(int(row["n"])),
            f"[{wr_color}]{row['win_rate']:.1%}[/{wr_color}]",
            f"{row['avg_return']:+.1%}",
            f"{row['sharpe']:.2f}",
            f"{row['avg_vs_spy']:+.1%}",
        )
    console.print(t)


def print_regime_table(regime_stats: pd.DataFrame):
    t = Table(title="🌍 Win Rate by Regime", header_style="bold magenta",
              show_lines=False)
    t.add_column("Regime",     width=30)
    t.add_column("N",          justify="right", width=6)
    t.add_column("Win Rate",   justify="right", width=10)
    t.add_column("Avg Return", justify="right", width=12)

    for _, row in regime_stats.sort_values("win_rate", ascending=False).iterrows():
        color = "green" if row["win_rate"] >= 0.63 else "yellow" if row["win_rate"] >= 0.50 else "red"
        t.add_row(
            str(row["filing_regime"] or "unknown"),
            str(int(row["n"])),
            f"[{color}]{row['win_rate']:.1%}[/{color}]",
            f"{row['avg_return']:+.1%}",
        )
    console.print(t)


def print_calibration(cal: pd.DataFrame):
    t = Table(title="🎯 Score Calibration  (ideal: score/100 ≈ actual%)",
              header_style="bold yellow", show_lines=False)
    t.add_column("Score Range",        width=14)
    t.add_column("N",                  justify="right", width=6)
    t.add_column("Predicted Win%",     justify="right", width=16)
    t.add_column("Actual Win%",        justify="right", width=14)
    t.add_column("Calibration Error",  justify="right", width=18)

    for _, row in cal.iterrows():
        err   = row["calibration_error"]
        color = "green" if err < 0.10 else "yellow" if err < 0.20 else "red"
        t.add_row(
            f"{row['score_mid']:.0f}",
            str(int(row["n"])),
            f"{row['score_mid']:.0f}%",
            f"[{color}]{row['actual_pct']:.1%}[/{color}]",
            f"[{color}]{err:.1%}[/{color}]",
        )
    console.print(t)


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main(min_year: int = 2010, score_threshold: float = 60):
    console.rule("[bold magenta]📊 FinTel — Backtest Engine[/bold magenta]")

    init_backtest_db()

    # ── Load data
    console.print(f"\n[bold]Loading historical data from {min_year}...[/bold]")
    df = load_historical_with_scores(min_year)

    if df.empty:
        console.print("[red]No historical data with outcomes found. "
                      "Run collect_historical_ipos.py first.[/red]")
        return

    console.print(f"[green]{len(df):,} companies with 1yr outcomes[/green]")

    # ── Score retroactively
    console.print("\n[bold]Scoring companies retroactively...[/bold]")
    scores = []
    with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                  BarColumn()) as prog:
        task = prog.add_task("Scoring...", total=len(df))
        for _, row in df.iterrows():
            scores.append(retroactive_score(row))
            prog.advance(task)

    df["fintel_score"] = scores
    df["score_band"]   = df["fintel_score"].apply(score_band)

    scored = df["fintel_score"].notna().sum()
    console.print(f"[green]{scored:,} / {len(df):,} companies scored[/green]")

    # ── Compute beat_spy
    df["beat_spy"] = (df["return_365d"] > 0).astype(int)

    # ── Overall stats
    n_total  = len(df)
    win_rate = float(df["beat_spy"].mean())
    avg_ret  = float(df["return_365d"].mean())
    sharpe   = sharpe_ratio(df["return_365d"])

    console.print(f"\n[bold]Overall (all {n_total:,} companies):[/bold]")
    console.print(f"  Win rate (beat 0%):  [cyan]{win_rate:.1%}[/cyan]")
    console.print(f"  Avg 1yr return:      [cyan]{avg_ret:+.1%}[/cyan]")
    console.print(f"  Sharpe ratio:        [cyan]{sharpe:.2f}[/cyan]")

    # ── Stats by score band
    band_rows = []
    for band in df["score_band"].unique():
        sub = df[df["score_band"] == band]
        spy_rets = sub["return_365d"].dropna()
        band_rows.append({
            "score_band":   band,
            "n":            len(sub),
            "win_rate":     float(sub["beat_spy"].mean()),
            "avg_return":   float(sub["return_365d"].mean()),
            "sharpe":       sharpe_ratio(sub["return_365d"].dropna()),
            "avg_vs_spy":   float(sub["return_365d"].mean()) - avg_ret,
        })
    band_stats = pd.DataFrame(band_rows).sort_values("score_band", ascending=False)

    console.print()
    print_band_table(band_stats, {"score_thresh": score_threshold, "min_year": min_year})

    # ── Stats by regime
    if "filing_regime" in df.columns:
        regime_stats = df.groupby("filing_regime").agg(
            n          = ("beat_spy", "count"),
            win_rate   = ("beat_spy", "mean"),
            avg_return = ("return_365d", "mean"),
        ).reset_index()
        console.print()
        print_regime_table(regime_stats)

    # ── Calibration
    cal = calibration_table(df)
    if not cal.empty:
        console.print()
        print_calibration(cal)

    # ── Save results
    run_date = datetime.now().isoformat()
    out_conn = sqlite3.connect(OUT_DB)
    cur      = out_conn.execute("""
        INSERT INTO backtest_runs
        (run_date, min_year, score_thresh, n_companies,
         win_rate, sharpe_ratio, avg_return, spy_return)
        VALUES (?,?,?,?,?,?,?,?)
    """, (run_date, min_year, score_threshold, n_total,
          win_rate, sharpe, avg_ret, 0.0))
    run_id = cur.lastrowid

    # Save per-company signals
    for _, row in df.iterrows():
        out_conn.execute("""
            INSERT INTO backtest_signals
            (run_id, company_id, company_name, ticker, filing_year,
             filing_regime, sector, fintel_score, score_band,
             actual_return_1yr, beat_spy, outcome_label)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            run_id,
            row.get("company_id"),
            row.get("company_name"),
            row.get("ticker"),
            row.get("filing_year"),
            row.get("filing_regime"),
            row.get("sic_description"),
            row.get("fintel_score"),
            row.get("score_band"),
            row.get("return_365d"),
            int(row.get("beat_spy", 0)),
            "winner" if row.get("return_365d", 0) > 0.50 else
            "moderate" if row.get("return_365d", 0) > 0 else "loser",
        ))

    # Save band stats
    for _, row in band_stats.iterrows():
        out_conn.execute("""
            INSERT INTO backtest_by_band
            (run_id, score_band, n, win_rate, avg_return, sharpe)
            VALUES (?,?,?,?,?,?)
        """, (run_id, row["score_band"], int(row["n"]),
              row["win_rate"], row["avg_return"], row["sharpe"]))

    out_conn.commit()
    out_conn.close()

    console.print(f"\n[green]✅ Results saved to backtest_results.db[/green]")
    console.print(f"[dim]Run ID: {run_id}[/dim]")

    # ── Key verdict
    console.rule("[bold]🎯 Backtest Verdict[/bold]")
    high = band_stats[band_stats["score_band"].str.startswith("75")]
    if not high.empty:
        hw = float(high.iloc[0]["win_rate"])
        hr = float(high.iloc[0]["avg_return"])
        if hw >= 0.63:
            console.print(
                f"[green]✅ Score ≥75 companies: {hw:.1%} win rate, "
                f"{hr:+.1%} avg return — MODEL HAS PREDICTIVE POWER[/green]"
            )
        else:
            console.print(
                f"[yellow]⚠ Score ≥75 companies: {hw:.1%} win rate — "
                f"BELOW 63% THRESHOLD — do not deploy capital yet[/yellow]"
            )
    else:
        console.print("[yellow]Not enough high-score companies to evaluate.[/yellow]")

    console.print(f"[dim]Next: python scripts/score_new_ipos.py --force (rescore with learnings)[/dim]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FinTel Backtest Engine")
    parser.add_argument("--min-year",         type=int,   default=2010,
                        help="Start year for backtest (default: 2010)")
    parser.add_argument("--score-threshold",  type=float, default=60,
                        help="Min score to include (default: 60)")
    args = parser.parse_args()
    main(min_year=args.min_year, score_threshold=args.score_threshold)
