"""
AGENT 1: IPO SCOUT
==================
Finds new IPO filings on SEC EDGAR, classifies them with local AI,
saves results to your database, and prints a summary table.

Usage:
    # ONE-TIME historical sweep (run this first, ever):
    python -m agents.ipo_scout --historical

    # Daily incremental update (auto-detects last scan date):
    python -m agents.ipo_scout --incremental

    # Manual scan for a specific window:
    python -m agents.ipo_scout --days 60
    python -m agents.ipo_scout --days 60 --min-score 40

Scan Modes Explained:
    --historical   : Pulls 365 days of filings. Run ONCE to build your baseline DB.
                     Tagged as 'historical' in scan_runs table.
    --incremental  : Reads last_scan_date from DB, fetches only NEW filings since then.
                     Safe to run daily — never re-fetches data you already have.
    --days N       : Manual override. Fetches last N days. Tagged as 'manual'.
"""

import re
import sys, os, time, argparse
from datetime import datetime, timedelta

import requests
import yfinance as yf
import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.db  import init_database, save_ipo_filing, get_last_scan_date, log_scan_run
from utils.llm import check_ollama_running, classify_company_sector

try:
    from config.settings import IPO_LOOKBACK_DAYS, IPO_MIN_SCORE_THRESHOLD, TRACKED_SECTORS
except ImportError:
    IPO_LOOKBACK_DAYS       = 30
    IPO_MIN_SCORE_THRESHOLD = 50
    TRACKED_SECTORS         = [
        "artificial_intelligence", "quantum_computing", "semiconductors_gan",
        "drone_aviation", "pharma_biotech", "defense_tech",
        "clean_energy", "cybersecurity", "space_tech"
    ]

console = Console()

SEC_HEADERS = {
    "User-Agent":      "FinTel Research Tool uniquestar333@gmail.com",
    "Accept":          "application/json",
    "Accept-Encoding": "gzip, deflate",
}

SEC_HEADERS_DATA = {
    "User-Agent":      "FinTel Research Tool uniquestar333@gmail.com",
    "Accept-Encoding": "gzip, deflate",
    "Host":            "data.sec.gov"
}


# ------------------------------------------------------------------
# Calendar helpers (module-level so they can be imported elsewhere)
# ------------------------------------------------------------------

def fetch_expected_listing_date(company_name: str) -> str | None:
    """Return expected listing date cached or scraped from multiple sources.

    Checks cache first; if missing scrapes Yahoo/Nasdaq IPO calendars and
    stores results for future use.
    """
    from utils.db import lookup_calendar, save_calendar

    cached = lookup_calendar(company_name)
    if cached:
        return cached

    date_val = None
    try:
        # use requests with a timeout to avoid long blocking
        resp = requests.get("https://finance.yahoo.com/calendar/ipo", timeout=10)
        tables = pd.read_html(resp.text)
        if tables:
            df = tables[0]
            for _, r in df.iterrows():
                comp = str(r.get("Company", ""))
                if company_name.lower() in comp.lower():
                    date_val = r.get("Expected IPO Date")
                    break
    except Exception:
        pass
    if not date_val:
        try:
            resp2 = requests.get("https://www.nasdaq.com/market-activity/ipos", timeout=10)
            tables = pd.read_html(resp2.text)
            if tables:
                df2 = tables[0]
                for _, r in df2.iterrows():
                    comp = str(r.iloc[0])
                    if company_name.lower() in comp.lower():
                        date_val = r.get("Expected IPO Date") or r.get("Expected Date")
                        break
        except Exception:
            pass
    if date_val:
        save_calendar(company_name, date_val, source="scrape")
    return date_val


def refresh_calendar_for_filings() -> int:
    """Populate missing expected_listing_date values for all filings."""
    from utils.db import get_connection, set_expected_listing_date
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, company_name FROM ipo_filings WHERE expected_listing_date IS NULL")
    rows = c.fetchall()
    conn.close()
    count = 0
    for fid, name in rows:
        exp = fetch_expected_listing_date(name)
        if exp:
            set_expected_listing_date(fid, exp)
            count += 1
    return count



# ── STEP 1: FETCH FILINGS FROM SEC EDGAR ─────────────────────────────────────

def fetch_s1_filings(start_date: str, end_date: str):
    """
    Fetch S-1/F-1 filings using EDGAR full-text search JSON API.

    WHY EXPLICIT DATES (not days_back):
    The incremental mode needs to fetch from an exact date — the day after
    the last scan completed. Using days_back would cause gaps or overlaps.
    Explicit start/end dates make the fetch window precise and auditable.

    WHY JSON API: The old RSS/browse-edgar endpoint returns empty results.
    The efts.sec.gov search API is what EDGAR's own search page uses —
    it returns structured JSON with real company names, CIKs, and dates.

    Args:
        start_date: 'YYYY-MM-DD' — start of the fetch window
        end_date:   'YYYY-MM-DD' — end of the fetch window (usually today)
    """
    filings  = []
    start_dt = start_date
    end_dt   = end_date



    for form in ["S-1", "F-1"]:
        try:
            url = (
                f"https://efts.sec.gov/LATEST/search-index"
                f"?q=%22{form}%22"
                f"&dateRange=custom&startdt={start_dt}&enddt={end_dt}"
                f"&forms={form}"
                f"&hits.hits._source=display_names,file_date,ciks,root_forms"
            )

            resp = requests.get(url, headers=SEC_HEADERS, timeout=20)

            if resp.status_code != 200:
                console.print(f"[yellow]{form}: SEC returned {resp.status_code}[/yellow]")
                continue

            data  = resp.json()
            hits  = data.get("hits", {}).get("hits", [])
            found = 0

            for hit in hits:
                try:
                    source     = hit.get("_source", {})
                    raw_name   = source.get("display_names", ["Unknown"])[0]
                    clean_name = re.split(r'\s+\(', raw_name)[0].strip()

                    if not clean_name or clean_name.lower() in ("", "unknown"):
                        continue

                    cik        = source.get("ciks", [""])[0]
                    filed_date = source.get("file_date", "")
                    filing_url = (
                        f"https://www.sec.gov/cgi-bin/browse-edgar"
                        f"?action=getcompany&CIK={cik}&type={form}&dateb=&owner=include&count=5"
                    )

                    expected = fetch_expected_listing_date(clean_name)
                    filings.append({
                        "company_name": clean_name,
                        "cik":          cik,
                        "filing_date":  filed_date,
                        "filing_type":  form,
                        "filing_url":   filing_url,
                        "ticker":       None,
                        "description":  "",
                        "expected_listing_date": expected,
                    })
                    found += 1

                except Exception:
                    continue

            console.print(f"[dim]  {form}: {found} filings[/dim]")
            time.sleep(0.5)

        except Exception as e:
            console.print(f"[yellow]Warning fetching {form}: {e}[/yellow]")
            continue

    return filings


# ── STEP 2: GET COMPANY DESCRIPTION FROM SEC ─────────────────────────────────

def fetch_description(cik, company_name):
    """
    Gets the company's SIC industry description from SEC.
    Gives Mistral richer context for accurate classification.
    """
    if not cik or not str(cik).isdigit():
        return f"Company: {company_name}"

    try:
        cik_padded = str(cik).zfill(10)
        resp = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik_padded}.json",
            headers=SEC_HEADERS_DATA,
            timeout=15
        )
        if resp.status_code == 200:
            data  = resp.json()
            parts = [f"Company: {data.get('name', company_name)}"]
            if data.get("sicDescription"):
                parts.append(f"Industry: {data['sicDescription']}")
            if data.get("stateOfIncorporation"):
                parts.append(f"State: {data['stateOfIncorporation']}")
            return " | ".join(parts)
    except Exception:
        pass
    finally:
        time.sleep(0.25)

    return f"Company: {company_name}"


# ── STEP 2B: AUTO TICKER LOOKUP ───────────────────────────────────────────────

def lookup_ticker(company_name: str) -> str:
    """
    Attempts to find a stock ticker for a company via yfinance search.

    WHY THIS MATTERS:
    SEC EDGAR filings don't include tickers — companies filing S-1/F-1
    haven't listed yet or are in the process. yfinance Search queries
    Yahoo Finance's symbol lookup, which often has the ticker even for
    recent IPOs and newly listed companies.

    WHY WE RETURN None GRACEFULLY:
    Many companies in our scan are pre-IPO, foreign, or too small to
    appear in Yahoo Finance. Returning None is correct — we don't want
    to assign a wrong ticker. Signal Analyst skips companies with no ticker.

    WHY time.sleep(0.3):
    Yahoo Finance rate-limits aggressive requests. A small delay prevents
    getting temporarily blocked during bulk scans of 100+ companies.
    """
    if not company_name or company_name.lower() == "unknown":
        return None

    try:
        search  = yf.Search(company_name, max_results=1)
        quotes  = search.quotes
        if quotes:
            symbol = quotes[0].get("symbol", None)
            # Basic sanity check — reject clearly wrong results
            # (yfinance sometimes returns unrelated tickers for obscure names)
            if symbol and len(symbol) <= 6 and symbol.isalpha():
                return symbol
    except Exception:
        pass
    finally:
        time.sleep(0.3)

    return None


# ── STEP 3: DISPLAY RESULTS ───────────────────────────────────────────────────

def display_results(filings, min_score):
    """Print a colour-coded results table sorted by score."""
    interesting = sorted(
        [f for f in filings if (f.get("interest_score") or 0) >= min_score],
        key=lambda x: x.get("interest_score", 0),
        reverse=True
    )

    if not interesting:
        console.print(f"\n[yellow]No companies scored above {min_score}.[/yellow]")
        console.print("[dim]Try: python -m agents.ipo_scout --min-score 30[/dim]")

        top5 = sorted(filings, key=lambda x: x.get("interest_score", 0), reverse=True)[:5]
        if top5:
            console.print("\n[bold]Top 5 found (all scores):[/bold]")
            for f in top5:
                sector = (f.get("primary_sector") or "other").replace("_", " ").title()
                console.print(f"  [{f.get('interest_score',0):>3}] {f.get('company_name','?')[:45]}  —  {sector}")
        return

    table = Table(
        title=f"🔍 FinTel IPO Scout — {len(interesting)} Companies Found",
        header_style="bold cyan",
        border_style="blue",
        show_lines=True
    )
    table.add_column("Score",     width=7,  justify="center", style="bold")
    table.add_column("Company",   width=35)
    table.add_column("Sector",    width=25, style="cyan")
    table.add_column("Ticker",    width=8,  style="green")
    table.add_column("Filed",     width=12, style="dim")
    table.add_column("Rationale", width=38, style="dim")

    for f in interesting:
        score  = f.get("interest_score", 0)
        color  = "green" if score >= 75 else "yellow" if score >= 55 else "red"
        ticker = f.get("ticker") or "[dim]—[/dim]"
        table.add_row(
            f"[{color}]{score}[/{color}]",
            (f.get("company_name") or "?")[:34],
            (f.get("primary_sector") or "other").replace("_", " ").title()[:24],
            ticker,
            (f.get("filing_date") or "")[:10],
            (f.get("score_rationale") or "")[:37],
        )

    console.print("\n")
    console.print(table)
    console.print("\n[dim]Next: [bold]streamlit run dashboard/app.py[/bold] → http://localhost:8501[/dim]\n")


# ── MAIN ORCHESTRATOR ─────────────────────────────────────────────────────────

def run_scout(mode: str = "manual", days_back: int = None, min_score: int = None):
    """
    Orchestrates an IPO scan in one of three modes:

    mode='historical'  : One-time large scan (365 days). Run once to seed the DB.
    mode='incremental' : Reads last_scan_date from DB, fetches only new records.
                         Safe to run daily — never duplicates data.
    mode='manual'      : Fetches last N days (days_back param). Manual override.
    """
    if min_score is None: min_score = IPO_MIN_SCORE_THRESHOLD
    today      = datetime.now().strftime("%Y-%m-%d")
    started_at = datetime.now().isoformat()

    # ── Resolve scan date window based on mode ─────────────────────────────
    if mode == "historical":
        lookback   = 365
        start_date = (datetime.now() - timedelta(days=lookback)).strftime("%Y-%m-%d")
        end_date   = today
        console.rule("[bold magenta]🗄️  FinTel IPO Scout — HISTORICAL SCAN[/bold magenta]")
        console.print(f"[dim]One-time baseline scan: {start_date} → {end_date}[/dim]")
        console.print("[yellow]This scan may take 10–20 minutes. Run once only.[/yellow]\n")

    elif mode == "incremental":
        last_date = get_last_scan_date()
        if last_date is None:
            console.print("[bold yellow]⚠️  No previous scan found in database.[/bold yellow]")
            console.print("Run a historical scan first: [bold]python -m agents.ipo_scout --historical[/bold]")
            return []
        start_dt   = datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=1)
        start_date = start_dt.strftime("%Y-%m-%d")
        end_date   = today
        if start_date >= end_date:
            console.print(f"[green]✅ Already up to date. Last scan: {last_date}[/green]")
            return []
        console.rule("[bold blue]🔄 FinTel IPO Scout — INCREMENTAL SCAN[/bold blue]")
        console.print(f"[dim]Fetching new filings only: {start_date} → {end_date}[/dim]")
        console.print(f"[dim]Last scan was: {last_date}[/dim]\n")

    else:  # manual
        if days_back is None: days_back = IPO_LOOKBACK_DAYS
        start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        end_date   = today
        console.rule("[bold blue]🧠 FinTel IPO Scout — MANUAL SCAN[/bold blue]")
        console.print(f"[dim]Scanning: {start_date} → {end_date} | Min score: {min_score}[/dim]\n")

    # ── Check Ollama ────────────────────────────────────────────────────────
    console.print("Checking local AI (Ollama)...")
    if not check_ollama_running():
        console.print("[bold red]❌ Ollama not running![/bold red]")
        console.print("Fix: open a NEW Command Prompt and run: [bold]ollama serve[/bold]")
        return []
    console.print("[green]✅ Ollama running[/green]\n")

    init_database()

    with Progress(SpinnerColumn(), TextColumn("{task.description}")) as p:
        t = p.add_task(f"Fetching from SEC EDGAR ({start_date} → {end_date})...", total=None)
        filings = fetch_s1_filings(start_date, end_date)
        p.remove_task(t)

    seen, clean = set(), []
    for f in filings:
        key = f["company_name"].lower().strip()
        if key not in seen and key not in ("", "unknown"):
            seen.add(key)
            clean.append(f)

    console.print(f"Found [bold]{len(clean)}[/bold] unique companies to analyse\n")

    if not clean:
        console.print("[yellow]No filings found. Try --days 90[/yellow]")
        return []

    processed    = []
    tickers_found = 0

    with Progress(SpinnerColumn(), TextColumn("{task.description}")) as p:
        for i, filing in enumerate(clean):
            name = filing["company_name"]
            t    = p.add_task(f"[{i+1}/{len(clean)}] {name[:45]}...", total=None)
            try:
                filing["description"] = fetch_description(filing.get("cik", ""), name)
                result = classify_company_sector(name, filing["description"], TRACKED_SECTORS)

                filing.update({
                    "primary_sector":    result["primary_sector"],
                    "secondary_sector":  result["secondary_sector"],
                    "sector_confidence": result["confidence"],
                    "interest_score":    result["interest_score"],
                    "score_rationale":   result["score_rationale"],
                    "business_summary":  result["reasoning"],
                    "status":            "new",
                })

                # ── AUTO TICKER LOOKUP ─────────────────────────────────────
                # Only attempt lookup for companies scoring above threshold
                # — saves time skipping low-score companies we won't track.
                if (result.get("interest_score") or 0) >= min_score:
                    ticker = lookup_ticker(name)
                    if ticker:
                        filing["ticker"] = ticker
                        tickers_found += 1

                save_ipo_filing(filing)
                processed.append(filing)
                time.sleep(0.3)

            except Exception as e:
                console.print(f"[red]Error on {name}: {e}[/red]")
            finally:
                p.remove_task(t)

    display_results(processed, min_score)

    errors_count = len(clean) - len(processed)
    status       = "success" if errors_count == 0 else "partial"
    above        = [f for f in processed if (f.get("interest_score") or 0) >= min_score]

    log_scan_run(
        run_type           = mode,
        scan_from          = start_date,
        scan_to            = end_date,
        filings_found      = len(clean),
        filings_classified = len(processed),
        errors             = errors_count,
        status             = status,
        started_at         = started_at,
    )

    console.print(
        f"[bold]Done:[/bold] {len(processed)} processed | "
        f"[green]{len(above)} above score {min_score}[/green] | "
        f"[cyan]{tickers_found} tickers auto-assigned[/cyan] | "
        f"saved to fintel.db | mode=[cyan]{mode}[/cyan]"
    )
    if mode == "incremental":
        console.print(f"[dim]Next incremental scan will fetch from: [bold]{end_date}[/bold] onwards[/dim]")

    # ensure any missing listing dates get filled after the scan
    try:
        nref = refresh_calendar_for_filings()
        console.print(f"[dim]Calendar refreshed for {nref} additional companies[/dim]")
    except Exception:
        pass

    return processed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="FinTel IPO Scout",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  First-time setup (run once):  python -m agents.ipo_scout --historical
  Daily update:                 python -m agents.ipo_scout --incremental
  Manual window:                python -m agents.ipo_scout --days 60
"""
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--historical",
        action="store_true",
        help="One-time 365-day baseline scan. Run once to seed the database."
    )
    mode_group.add_argument(
        "--incremental",
        action="store_true",
        help="Fetch only new filings since last scan. Safe to run daily."
    )
    mode_group.add_argument(
        "--days",
        type=int,
        default=None,
        help="Manual: scan last N days (default 30 if no mode specified)."
    )

    parser.add_argument(
        "--min-score",
        type=int,
        default=None,
        help="Minimum interest score to display in results table (default 50)."
    )

    args = parser.parse_args()

    if args.historical:
        run_scout(mode="historical", min_score=args.min_score)
    elif args.incremental:
        run_scout(mode="incremental", min_score=args.min_score)
    else:
        run_scout(mode="manual", days_back=args.days, min_score=args.min_score)
