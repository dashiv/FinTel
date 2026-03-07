"""
PHASE 5 — STEP 1: HISTORICAL IPO DATA COLLECTION (v3)
======================================================
One-time script. Resumes safely if interrupted.

Databases created:
  fintel_events.db      ← reference layer (regimes, tech cycles, events)
  fintel_historical.db  ← IPO data with foreign keys to events

Run: python scripts/collect_historical_ipos.py
"""

import os, sys, re, time, sqlite3, requests
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn
from rich.table import Table
from loguru import logger

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.events_db import (
    init_events_db, get_regime, get_tech_cycle, get_events_in_window
)

console = Console()

ROOT    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "fintel_historical.db")

SEC_HEADERS = {
    "User-Agent":      "FinTel Research Tool uniquestar333@gmail.com",
    "Accept":          "application/json",
    "Accept-Encoding": "gzip, deflate",
}
SEC_HEADERS_DATA = {
    "User-Agent":      "FinTel Research Tool uniquestar333@gmail.com",
    "Accept-Encoding": "gzip, deflate",
    "Host":            "data.sec.gov",
}

FETCH_YEARS = list(range(1996, datetime.now().year + 1))


# ── CHECKPOINT SCHEDULE ───────────────────────────────────────────────────────

def generate_checkpoints(max_days: int) -> list[int]:
    fine   = [30, 60, 90, 120, 180, 240, 365, 548, 730]
    coarse = list(range(910, max_days + 1, 180))   # 730+180 = 910, then every 180d
    return sorted(set(fine + coarse))


# ── DATABASE SETUP ────────────────────────────────────────────────────────────

def init_historical_db():
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS historical_ipos (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name        TEXT NOT NULL,
            cik                 TEXT,
            filing_date         TEXT,
            filing_type         TEXT,
            ticker              TEXT,
            sic_description     TEXT,
            state               TEXT,
            filing_regime       TEXT,
            filing_tech_cycle   TEXT,
            ticker_found        INTEGER DEFAULT 0,
            ipo_price           REAL,
            total_checkpoints   INTEGER DEFAULT 0,
            data_span_days      INTEGER DEFAULT 0,
            created_at          TEXT DEFAULT (datetime('now')),
            UNIQUE(cik, filing_date)
        )
    """)

    # One row per company per time checkpoint
    # Both macro regime AND tech cycle stored at checkpoint date
    c.execute("""
        CREATE TABLE IF NOT EXISTS price_checkpoints (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id            INTEGER NOT NULL,
            ticker                TEXT,
            days_offset           INTEGER,
            checkpoint_date       TEXT,
            price                 REAL,
            return_vs_ipo         REAL,
            regime_at_checkpoint  TEXT,
            tech_cycle_at_checkpoint TEXT,
            outcome_label         TEXT,
            FOREIGN KEY (company_id) REFERENCES historical_ipos(id)
        )
    """)

    # Which events fell in each company's data window
    # References fintel_events.db event_id by text (cross-DB foreign key by convention)
    c.execute("""
        CREATE TABLE IF NOT EXISTS company_event_flags (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id        INTEGER,
            event_id          TEXT,
            event_date        TEXT,
            event_category    TEXT,
            event_name        TEXT,
            days_into_window  INTEGER,
            FOREIGN KEY (company_id) REFERENCES historical_ipos(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS collection_runs (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            year                INTEGER UNIQUE,
            filings_fetched     INTEGER,
            tickers_found       INTEGER,
            checkpoints_saved   INTEGER,
            event_flags_saved   INTEGER,
            status              TEXT,
            started_at          TEXT,
            completed_at        TEXT
        )
    """)

    conn.commit()
    conn.close()


def get_done_years():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT year FROM collection_runs WHERE status='complete'"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def save_filing(record: dict) -> int | None:
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()
    c.execute("""
        INSERT OR IGNORE INTO historical_ipos
            (company_name, cik, filing_date, filing_type,
             ticker, sic_description, state,
             filing_regime, filing_tech_cycle,
             ticker_found, ipo_price)
        VALUES
            (:company_name, :cik, :filing_date, :filing_type,
             :ticker, :sic_description, :state,
             :filing_regime, :filing_tech_cycle,
             :ticker_found, :ipo_price)
    """, record)
    conn.commit()
    row = conn.execute(
        "SELECT id FROM historical_ipos WHERE cik=? AND filing_date=?",
        (record["cik"], record["filing_date"])
    ).fetchone()
    conn.close()
    return row[0] if row else None


def save_checkpoints(company_id: int, checkpoints: list[dict]):
    if not checkpoints:
        return
    conn = sqlite3.connect(DB_PATH)
    conn.executemany("""
        INSERT INTO price_checkpoints
            (company_id, ticker, days_offset, checkpoint_date,
             price, return_vs_ipo,
             regime_at_checkpoint, tech_cycle_at_checkpoint,
             outcome_label)
        VALUES
            (:company_id, :ticker, :days_offset, :checkpoint_date,
             :price, :return_vs_ipo,
             :regime_at_checkpoint, :tech_cycle_at_checkpoint,
             :outcome_label)
    """, checkpoints)
    conn.execute("""
        UPDATE historical_ipos
        SET total_checkpoints=?, data_span_days=?, ipo_price=?
        WHERE id=?
    """, (len(checkpoints),
          checkpoints[-1]["days_offset"],
          checkpoints[0]["price"],
          company_id))
    conn.commit()
    conn.close()


def save_event_flags(company_id: int, filing_date: str, max_days: int) -> int:
    """
    Query fintel_events.db for events in company's data window.
    Save flagged events to fintel_historical.db company_event_flags.
    Returns count of events flagged.
    """
    if not filing_date:
        return 0

    filing_dt  = datetime.strptime(filing_date, "%Y-%m-%d")
    window_end = (filing_dt + timedelta(days=max_days)).strftime("%Y-%m-%d")

    events = get_events_in_window(filing_date, window_end)
    if not events:
        return 0

    flags = []
    for ev in events:
        ev_dt    = datetime.strptime(ev["event_date"], "%Y-%m-%d")
        days_in  = (ev_dt - filing_dt).days
        flags.append((
            company_id,
            ev["event_id"],
            ev["event_date"],
            ev["category"],
            ev["name"],
            days_in
        ))

    conn = sqlite3.connect(DB_PATH)
    conn.executemany("""
        INSERT INTO company_event_flags
            (company_id, event_id, event_date, event_category, event_name, days_into_window)
        VALUES (?,?,?,?,?,?)
    """, flags)
    conn.commit()
    conn.close()
    return len(flags)


def log_year(year, fetched, tickers, checkpoints, event_flags, status, started_at):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT OR REPLACE INTO collection_runs
            (year, filings_fetched, tickers_found, checkpoints_saved,
             event_flags_saved, status, started_at, completed_at)
        VALUES (?,?,?,?,?,?,?,?)
    """, (year, fetched, tickers, checkpoints, event_flags,
          status, started_at, datetime.now().isoformat()))
    conn.commit()
    conn.close()


# ── OUTCOME LABELLER ──────────────────────────────────────────────────────────

def label_outcome(r: float | None) -> str:
    if r is None:   return "unknown"
    if r >= 0.50:   return "strong_winner"
    if r >= 0.00:   return "moderate"
    if r >= -0.10:  return "flat"
    return "loser"


# ── SEC EDGAR ─────────────────────────────────────────────────────────────────

def fetch_year(year: int) -> list:
    filings = []
    for form in ["S-1", "F-1"]:
        try:
            url = (
                f"https://efts.sec.gov/LATEST/search-index"
                f"?q=%22{form}%22"
                f"&dateRange=custom"
                f"&startdt={year}-01-01&enddt={year}-12-31"
                f"&forms={form}"
                f"&hits.hits._source=display_names,file_date,ciks"
            )
            resp = requests.get(url, headers=SEC_HEADERS, timeout=30)
            if resp.status_code != 200:
                continue
            for hit in resp.json().get("hits", {}).get("hits", []):
                src  = hit.get("_source", {})
                name = re.split(r'\s+\(',
                    src.get("display_names", [""])[0])[0].strip()
                if not name or name.lower() == "unknown":
                    continue
                filings.append({
                    "company_name": name,
                    "cik":          src.get("ciks", [""])[0],
                    "filing_date":  src.get("file_date", ""),
                    "filing_type":  form,
                })
            time.sleep(0.4)
        except Exception as e:
            logger.warning(f"{year}/{form}: {e}")

    seen, clean = set(), []
    for f in filings:
        key = (f["cik"], f["filing_date"])
        if key not in seen and f["cik"]:
            seen.add(key)
            clean.append(f)
    return clean


def fetch_sec_meta(cik: str) -> dict:
    if not cik or not str(cik).isdigit():
        return {}
    try:
        resp = requests.get(
            f"https://data.sec.gov/submissions/CIK{str(cik).zfill(10)}.json",
            headers=SEC_HEADERS_DATA, timeout=15
        )
        if resp.status_code == 200:
            d = resp.json()
            return {
                "sic_description": d.get("sicDescription", ""),
                "state":           d.get("stateOfIncorporation", ""),
            }
    except Exception:
        pass
    finally:
        time.sleep(0.2)
    return {}


def lookup_ticker(name: str) -> str | None:
    try:
        results = yf.Search(name, max_results=1).quotes
        if results:
            sym = results[0].get("symbol", "")
            if sym and len(sym) <= 6 and sym.isalpha():
                return sym
    except Exception:
        pass
    finally:
        time.sleep(0.25)
    return None


# ── PRICE CHECKPOINT ENGINE ───────────────────────────────────────────────────

def build_price_checkpoints(ticker: str, filing_date: str,
                             company_id: int) -> list[dict]:
    if not ticker or not filing_date:
        return []
    try:
        filing_dt = datetime.strptime(filing_date, "%Y-%m-%d")
        today     = datetime.now()

        hist = yf.Ticker(ticker).history(
            start=filing_date,
            end=today.strftime("%Y-%m-%d"),
            auto_adjust=True
        )

        if hist.empty or len(hist) < 10:
            return []

        prices = hist["Close"]
        try:
            prices.index = prices.index.tz_localize(None)
        except Exception:
            try:
                prices.index = prices.index.tz_convert(None)
            except Exception:
                pass

        ipo_price = float(prices.iloc[0])
        if ipo_price <= 0:
            return []

        max_days     = (today - filing_dt).days
        checkpoints  = generate_checkpoints(max_days)

        rows = []
        for days in checkpoints:
            target = filing_dt + timedelta(days=days)
            future = prices[prices.index >= pd.Timestamp(target)]
            if future.empty:
                continue

            price          = float(future.iloc[0])
            chk_date       = future.index[0].strftime("%Y-%m-%d")
            return_vs_ipo  = (price - ipo_price) / ipo_price

            rows.append({
                "company_id":                company_id,
                "ticker":                    ticker,
                "days_offset":               days,
                "checkpoint_date":           chk_date,
                "price":                     round(price, 4),
                "return_vs_ipo":             round(return_vs_ipo, 6),
                "regime_at_checkpoint":      get_regime(chk_date),
                "tech_cycle_at_checkpoint":  get_tech_cycle(chk_date),
                "outcome_label":             label_outcome(return_vs_ipo),
            })
        return rows

    except Exception as e:
        logger.debug(f"Price build failed {ticker}: {e}")
        return []


# ── SUMMARY ───────────────────────────────────────────────────────────────────

def print_summary():
    conn = sqlite3.connect(DB_PATH)
    ipos = pd.read_sql("SELECT * FROM historical_ipos", conn)
    runs = pd.read_sql("SELECT * FROM collection_runs WHERE status='complete'", conn)
    conn.close()

    t = Table(title="📊 Collection Summary", header_style="bold cyan", show_lines=True)
    t.add_column("Metric", width=40, style="dim")
    t.add_column("Value",  width=15, justify="right", style="bold")

    total    = len(ipos)
    w_tick   = int(ipos["ticker_found"].sum()) if total else 0
    w_chk    = int((ipos["total_checkpoints"] > 0).sum()) if total else 0
    yr_done  = sorted(runs["year"].tolist()) if len(runs) else []

    t.add_row("Total filings",          str(total))
    t.add_row("Tickers found",          f"{w_tick} ({int(w_tick/total*100) if total else 0}%)")
    t.add_row("With price checkpoints", f"{w_chk} ({int(w_chk/total*100) if total else 0}%)")
    t.add_row("Years completed",        str(len(yr_done)))
    t.add_row("Year range",             f"{yr_done[0]}–{yr_done[-1]}" if yr_done else "—")

    console.print(t)


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    console.rule("[bold magenta]📚 FinTel Phase 5 — Historical Data Collection v3[/bold magenta]")

    # ── Step 0: Init both databases
    console.print("Initialising [bold]fintel_events.db[/bold]...")
    stats = init_events_db()
    console.print(
        f"  [green]✅[/green] Events DB ready: "
        f"{stats['events']} events | "
        f"{stats['regimes']} regimes | "
        f"{stats['tech_cycles']} tech cycles\n"
    )

    console.print(f"Initialising [bold]fintel_historical.db[/bold]...")
    init_historical_db()
    console.print(f"  [green]✅[/green] Historical DB ready\n")

    done_years = get_done_years()
    remaining  = [y for y in FETCH_YEARS if y not in done_years]

    if not remaining:
        console.print("[green]✅ All years complete.[/green]")
        print_summary()
        return

    console.print(f"[dim]DB: {DB_PATH}[/dim]")
    console.print(f"Years to collect: [bold]{remaining[0]}[/bold] → [bold]{remaining[-1]}[/bold]")
    if done_years:
        console.print(f"Already done: {sorted(done_years)}")
    console.print()

    for year in remaining:
        started_at = datetime.now().isoformat()
        console.rule(f"[cyan]{year}[/cyan]")

        with Progress(SpinnerColumn(), TextColumn("{task.description}")) as p:
            t = p.add_task(f"Fetching {year} from SEC EDGAR...", total=None)
            filings = fetch_year(year)
            p.remove_task(t)

        console.print(f"  [bold]{len(filings)}[/bold] unique filings")

        if not filings:
            log_year(year, 0, 0, 0, 0, "complete", started_at)
            continue

        yr_tickers = yr_checkpoints = yr_event_flags = 0

        with Progress(
            SpinnerColumn(), TextColumn("{task.description}"),
            BarColumn(), MofNCompleteColumn()
        ) as p:
            task = p.add_task(f"Enriching {year}...", total=len(filings))

            for filing in filings:
                name        = filing["company_name"]
                filing_date = filing["filing_date"]
                cik         = filing["cik"]

                meta          = fetch_sec_meta(cik)
                ticker        = lookup_ticker(name)
                if ticker:
                    yr_tickers += 1

                record = {
                    "company_name":     name,
                    "cik":              cik,
                    "filing_date":      filing_date,
                    "filing_type":      filing["filing_type"],
                    "ticker":           ticker,
                    "sic_description":  meta.get("sic_description", ""),
                    "state":            meta.get("state", ""),
                    "filing_regime":    get_regime(filing_date),
                    "filing_tech_cycle":get_tech_cycle(filing_date),
                    "ticker_found":     1 if ticker else 0,
                    "ipo_price":        None,
                }

                company_id = save_filing(record)

                if ticker and company_id:
                    filing_dt  = datetime.strptime(filing_date, "%Y-%m-%d") if filing_date else None
                    days_since = (datetime.now() - filing_dt).days if filing_dt else 0

                    if days_since >= 30:
                        checkpoints = build_price_checkpoints(ticker, filing_date, company_id)
                        if checkpoints:
                            save_checkpoints(company_id, checkpoints)
                            yr_checkpoints += len(checkpoints)

                            max_days         = checkpoints[-1]["days_offset"]
                            flags_saved      = save_event_flags(company_id, filing_date, max_days)
                            yr_event_flags  += flags_saved

                p.advance(task)

        log_year(year, len(filings), yr_tickers,
                 yr_checkpoints, yr_event_flags, "complete", started_at)

        console.print(
            f"  [green]✅ {year}:[/green] "
            f"{len(filings)} filings | "
            f"{yr_tickers} tickers | "
            f"{yr_checkpoints} checkpoints | "
            f"{yr_event_flags} event flags"
        )
        time.sleep(1.0)

    console.rule("[bold green]✅ Collection Complete[/bold green]")
    print_summary()
    console.print(f"\n[dim]fintel_events.db:     {os.path.join(ROOT, 'fintel_events.db')}[/dim]")
    console.print(f"[dim]fintel_historical.db: {DB_PATH}[/dim]")
    console.print("[dim]Next: python scripts/train_models.py[/dim]")


if __name__ == "__main__":
    main()
