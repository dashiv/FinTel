"""
utils/db.py
-----------
All database operations for FinTel.
Uses SQLite - a single file, no server needed.
Think of it like a programmable Excel workbook.
"""

import sqlite3, os, json
from datetime import datetime
import pandas as pd
from utils.logger import logger

try:
    from config.settings import DB_PATH
except ImportError:
    DB_PATH = "fintel.db"


def get_connection():
    """Open a connection to the SQLite database file."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # rows behave like dictionaries
    return conn


def init_database():
    """
    Create all tables if they don't already exist.
    Safe to run many times - won't delete existing data.
    """
    logger.info(f"Initialising database: {DB_PATH}")
    conn = get_connection()
    c = conn.cursor()

    # ── Table 1: Every IPO filing we discover ──────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS ipo_filings (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name     TEXT NOT NULL,
            ticker           TEXT,
            cik              TEXT UNIQUE,
            filing_date      TEXT,
            filing_type      TEXT,
            filing_url       TEXT,
            description      TEXT,
            business_summary TEXT,
            primary_sector   TEXT,
            secondary_sector TEXT,
            sector_confidence REAL,
            interest_score   INTEGER,
            score_rationale  TEXT,
            status           TEXT DEFAULT 'new',
            expected_listing_date TEXT,
            created_at       TEXT DEFAULT (datetime('now')),
            updated_at       TEXT DEFAULT (datetime('now'))
        )
    """)
    # in case we're upgrading an existing database from earlier versions
    try:
        c.execute("ALTER TABLE ipo_filings ADD COLUMN expected_listing_date TEXT")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE ipo_filings ADD COLUMN ai_summary TEXT")
    except Exception:
        pass

    # ── Table 2: Your active watchlist ─────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            filing_id            INTEGER REFERENCES ipo_filings(id),
            ticker               TEXT NOT NULL,
            company_name         TEXT NOT NULL,
            entry_rationale      TEXT,
            conviction_score     INTEGER,
            suggested_entry_low  REAL,
            suggested_entry_high REAL,
            target_price         REAL,
            recommended_hold_days INTEGER,
            tax_free_eligible    INTEGER DEFAULT 0,
            status               TEXT DEFAULT 'watching',
            created_at           TEXT DEFAULT (datetime('now')),
            updated_at           TEXT DEFAULT (datetime('now'))
        )
    """)

    # ── Table 3: Signal scores history ────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS signal_scores (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker            TEXT NOT NULL,
            analysis_date     TEXT NOT NULL,
            technical_score   INTEGER,
            sentiment_score   INTEGER,
            sector_score      INTEGER,
            fundamental_score INTEGER,
            composite_score   INTEGER,
            news_summary      TEXT,
            technical_summary TEXT,
            key_catalysts     TEXT,
            key_risks         TEXT,
            price_at_analysis REAL,
            rsi_14            REAL,
            created_at        TEXT DEFAULT (datetime('now'))
        )
    """)

    # ── Table 4: Your portfolio (paper + real) ─────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS portfolio (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker             TEXT NOT NULL,
            company_name       TEXT,
            entry_date         TEXT,
            entry_price        REAL,
            shares             REAL,
            total_invested_eur REAL,
            exit_date          TEXT,
            exit_price         REAL,
            current_price      REAL,
            unrealised_pnl_pct REAL,
            hold_days          INTEGER,
            tax_free_date      TEXT,
            is_tax_free        INTEGER DEFAULT 0,
            status             TEXT DEFAULT 'open',
            is_paper_trade     INTEGER DEFAULT 1,
            notes              TEXT,
            created_at         TEXT DEFAULT (datetime('now')),
            updated_at         TEXT DEFAULT (datetime('now'))
        )
    """)

    # ── Table 5: Log of every scan run ────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS scan_runs (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            run_type           TEXT,         -- 'historical' | 'incremental' | 'manual'
            scan_from_date     TEXT,         -- start of date range fetched
            scan_to_date       TEXT,         -- end of date range fetched
            started_at         TEXT,
            finished_at        TEXT,
            filings_found      INTEGER DEFAULT 0,
            filings_classified INTEGER DEFAULT 0,
            errors             INTEGER DEFAULT 0,
            status             TEXT          -- 'success' | 'failed' | 'partial'
        )
    """)

    # ── Table 6: Key-value metadata store ─────────────────────────────────
    # Stores things like last_scan_date so incremental scans know where to start.
    # Think of this as a settings table for the system itself.
    c.execute("""
        CREATE TABLE IF NOT EXISTS scan_metadata (
            key        TEXT PRIMARY KEY,
            value      TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    conn.commit()
    conn.close()
    logger.success("✅ Database ready")


def get_last_scan_date() -> str | None:
    """
    Returns the date of the most recently completed scan, or None if no scan has run.

    WHY THIS EXISTS:
    Incremental scans use this to know where to start fetching from.
    Instead of always fetching 30 days, we fetch from last_scan_date to today.
    This means we never re-fetch data we already have.

    Returns:
        Date string like '2026-03-04', or None if no scan has ever run.
    """
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT value FROM scan_metadata WHERE key = 'last_scan_date'")
        row = c.fetchone()
        return row["value"] if row else None
    except Exception:
        return None
    finally:
        conn.close()


def log_scan_run(run_type: str, scan_from: str, scan_to: str,
                 filings_found: int, filings_classified: int,
                 errors: int, status: str, started_at: str) -> None:
    """
    Records a completed scan run to the scan_runs table and updates last_scan_date.

    Args:
        run_type:           'historical', 'incremental', or 'manual'
        scan_from:          Start date of the scan (YYYY-MM-DD)
        scan_to:            End date of the scan (YYYY-MM-DD)
        filings_found:      Total filings fetched from SEC
        filings_classified: Filings successfully classified by AI
        errors:             Number of errors during classification
        status:             'success', 'failed', or 'partial'
        started_at:         ISO timestamp when the scan started
    """
    conn = get_connection()
    c = conn.cursor()
    try:
        finished_at = datetime.now().isoformat()

        # Log the scan run
        c.execute("""
            INSERT INTO scan_runs
              (run_type, scan_from_date, scan_to_date, started_at, finished_at,
               filings_found, filings_classified, errors, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (run_type, scan_from, scan_to, started_at, finished_at,
              filings_found, filings_classified, errors, status))

        # Update the last_scan_date metadata key (only on success or partial)
        if status in ("success", "partial"):
            c.execute("""
                INSERT INTO scan_metadata (key, value, updated_at)
                VALUES ('last_scan_date', ?, datetime('now'))
                ON CONFLICT(key) DO UPDATE SET
                    value      = excluded.value,
                    updated_at = datetime('now')
            """, (scan_to,))

        conn.commit()
        logger.info(f"Scan logged: {run_type} | {scan_from} → {scan_to} | {status}")
    except Exception as e:
        logger.error(f"Failed to log scan run: {e}")
        conn.rollback()
    finally:
        conn.close()


def save_ipo_filing(filing: dict) -> int:
    """Save one IPO filing. Updates it if we've seen the CIK before."""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO ipo_filings (
                company_name, ticker, cik, filing_date, filing_type,
                filing_url, description, business_summary,
                primary_sector, secondary_sector, sector_confidence,
                interest_score, score_rationale, status,
                expected_listing_date
            ) VALUES (
                :company_name,:ticker,:cik,:filing_date,:filing_type,
                :filing_url,:description,:business_summary,
                :primary_sector,:secondary_sector,:sector_confidence,
                :interest_score,:score_rationale,:status,
                :expected_listing_date
            )
            ON CONFLICT(cik) DO UPDATE SET
                business_summary         = excluded.business_summary,
                primary_sector           = excluded.primary_sector,
                interest_score           = excluded.interest_score,
                score_rationale          = excluded.score_rationale,
                expected_listing_date    = COALESCE(excluded.expected_listing_date, ipo_filings.expected_listing_date),
                updated_at               = datetime('now')
        """, {
            "company_name":      filing.get("company_name","Unknown"),
            "ticker":            filing.get("ticker"),
            "cik":               filing.get("cik"),
            "filing_date":       filing.get("filing_date"),
            "filing_type":       filing.get("filing_type"),
            "filing_url":        filing.get("filing_url"),
            "description":       filing.get("description"),
            "business_summary":  filing.get("business_summary"),
            "primary_sector":    filing.get("primary_sector"),
            "secondary_sector":  filing.get("secondary_sector"),
            "sector_confidence": filing.get("sector_confidence"),
            "interest_score":    filing.get("interest_score"),
            "score_rationale":   filing.get("score_rationale"),
            "status":            filing.get("status","new"),
            "expected_listing_date": filing.get("expected_listing_date"),
        })
        conn.commit()
        return c.lastrowid
    except Exception as e:
        logger.error(f"DB save failed for {filing.get('company_name')}: {e}")
        conn.rollback()
        return -1
    finally:
        conn.close()


def get_recent_filings(days: int = 30, min_score: int = 0) -> list:
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM ipo_filings
        WHERE filing_date >= date('now', '-' || ? || ' days')
        AND   (interest_score >= ? OR interest_score IS NULL)
        ORDER BY interest_score DESC, filing_date DESC
    """, (days, min_score))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_watchlist(min_score: int = 0) -> list:
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT DISTINCT w.filing_id, w.id, w.ticker, w.company_name, w.entry_rationale,
               w.conviction_score, w.suggested_entry_low, w.suggested_entry_high,
               w.target_price, w.recommended_hold_days, w.tax_free_eligible,
               w.status, w.created_at, w.updated_at,
               f.primary_sector, f.filing_date, f.filing_url
        FROM watchlist w
        LEFT JOIN ipo_filings f ON w.filing_id = f.id
        WHERE w.conviction_score >= ? AND w.status = 'watching'
        ORDER BY w.conviction_score DESC
    """, (min_score,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def is_in_watchlist(filing_id: int) -> bool:
    """Return True if the given filing_id is currently on the active watchlist."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT 1 FROM watchlist WHERE filing_id = ? AND status = 'watching'", (filing_id,))
    result = c.fetchone() is not None
    conn.close()
    return result


def set_ai_summary(filing_id: int, text: str) -> bool:
    """Save an AI-generated summary to the filing row.

    Returns ``True`` if an existing row was updated, ``False`` if no such
    filing exists. Previous behaviour always returned ``True`` which made it
    impossible for callers/tests to detect a missing record.
    """
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("UPDATE ipo_filings SET ai_summary = ?, updated_at = datetime('now') WHERE id = ?", (text, filing_id))
        # rowcount will be 0 if no row matched the WHERE clause
        updated = c.rowcount > 0
        conn.commit()
        return updated
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()


def get_ai_summary(filing_id: int) -> str:
    """Fetch AI summary for a filing. Returns empty string if not found."""
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT ai_summary FROM ipo_filings WHERE id = ?", (filing_id,))
        row = c.fetchone()
        conn.close()
        return row[0] if row and row[0] else ''
    except Exception:
        return ''


def get_tracked_companies() -> list:
    """
    Returns a list of companies that currently have a listed ticker
    and an interest score >= 70 from the initial IPO scout.
    These are the candidates for daily Signal Analysis.
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT id, ticker, company_name, primary_sector, interest_score 
        FROM ipo_filings 
        WHERE ticker IS NOT NULL AND ticker != '' 
        AND interest_score >= 70
    """)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def save_signal_score(signal: dict) -> int:
    """
    Saves a generated trading signal to the database.
    """
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO signal_scores (
                ticker, analysis_date, technical_score, sentiment_score, 
                sector_score, fundamental_score, composite_score, 
                news_summary, technical_summary, key_catalysts, key_risks, 
                price_at_analysis, rsi_14
            ) VALUES (
                :ticker, :analysis_date, :technical_score, :sentiment_score, 
                :sector_score, :fundamental_score, :composite_score, 
                :news_summary, :technical_summary, :key_catalysts, :key_risks, 
                :price_at_analysis, :rsi_14
            )
        """, signal)
        conn.commit()
        return c.lastrowid
    except Exception as e:
        logger.error(f"Failed to save signal for {signal.get('ticker')}: {e}")
        conn.rollback()
        return -1
    finally:
        conn.close()


def get_portfolio(open_only: bool = True) -> list:
    """Return portfolio positions.

    Args:
        open_only: if True (default) returns only status='open'; otherwise returns all.
    """
    conn = get_connection()
    c = conn.cursor()
    if open_only:
        c.execute("SELECT * FROM portfolio WHERE status='open' ORDER BY entry_date DESC")
    else:
        c.execute("SELECT * FROM portfolio ORDER BY entry_date DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_closed_positions() -> list:
    """Return closed positions with computed realised P/L percentages and euros."""
    rows = get_portfolio(open_only=False)
    result = []
    for p in rows:
        if p.get('status') == 'closed' and p.get('exit_price') is not None:
            entry = p.get('entry_price', 0) or 0
            exitp = p.get('exit_price', 0) or 0
            shares = p.get('shares', 0) or 0
            pnl_pct = ((exitp - entry) / entry * 100) if entry else 0
            pnl_eur = (exitp - entry) * shares
            p['realised_pnl_pct'] = pnl_pct
            p['realised_pnl_eur'] = pnl_eur
            result.append(p)
    return result


def refresh_portfolio_metrics():
    """Update open positions with current price, unrealised P/L and hold days."""
    try:
        import yfinance as yf
        from datetime import datetime
    except ImportError:
        return 0

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, ticker, entry_price, shares, entry_date FROM portfolio WHERE status='open'")
    rows = c.fetchall()
    updated = 0
    for row in rows:
        pos_id, ticker, entry_price, shares, entry_date = row
        try:
            df = yf.Ticker(ticker).history(period="1d")
            if df.empty:
                continue
            price = df['Close'].iloc[-1]
            unreal = ((price - entry_price) / entry_price) * 100 if entry_price else 0
            hold_days = (datetime.now() - datetime.strptime(entry_date, "%Y-%m-%d")).days
            c.execute(
                "UPDATE portfolio SET unrealised_pnl_pct = ?, hold_days = ? WHERE id = ?",
                (unreal, hold_days, pos_id)
            )
            updated += 1
        except Exception:
            continue
    conn.commit()
    conn.close()
    return updated


def add_position(ticker: str, company_name: str, entry_date: str, entry_price: float, shares: float, is_paper: bool = True) -> int:
    """Insert a new position into portfolio and return its id."""
    try:
        conn = get_connection()
        c = conn.cursor()
        tax_free = datetime.strptime(entry_date, "%Y-%m-%d") + pd.Timedelta(days=183)
        c.execute(
            """
            INSERT INTO portfolio(ticker, company_name, entry_date, entry_price, shares, total_invested_eur, tax_free_date, is_paper_trade)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (ticker, company_name, entry_date, entry_price, shares, entry_price * shares, tax_free.strftime("%Y-%m-%d"), 1 if is_paper else 0)
        )
        conn.commit()
        return c.lastrowid
    except Exception as e:
        logger.error(f"Failed to add portfolio position {ticker}: {e}")
        conn.rollback()
        return -1
    finally:
        conn.close()


def close_position(pos_id: int, exit_date: str, exit_price: float) -> bool:
    """Mark an open position as closed, calculate P&L and hold days."""
    try:
        conn = get_connection()
        c = conn.cursor()
        # compute hold days and unrealised pnl
        c.execute("SELECT entry_date, entry_price, shares FROM portfolio WHERE id = ?", (pos_id,))
        row = c.fetchone()
        if not row:
            return False
        entry_date, entry_price, shares = row
        hold_days = (datetime.strptime(exit_date, "%Y-%m-%d") - datetime.strptime(entry_date, "%Y-%m-%d")).days
        unreal = ((exit_price - entry_price) / entry_price) * 100
        c.execute(
            """
            UPDATE portfolio
            SET exit_date = ?, exit_price = ?, unrealised_pnl_pct = ?, hold_days = ?, status='closed', updated_at=datetime('now')
            WHERE id = ?
            """,
            (exit_date, exit_price, unreal, hold_days, pos_id)
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to close position {pos_id}: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Watchlist / Portfolio helpers
# ---------------------------------------------------------------------------

def add_to_watchlist(filing_id: int, conviction_score: int = 0, entry_rationale: str = "") -> int:
    """Adds an IPO filing to the watchlist. Returns the watchlist row id or -1 on error.

    - Ensures the filing has a ticker (non-null).
    - Prevents duplicate active entries (status='watching'); if already present,
      the existing row id is returned and no new row is inserted.
    - If the ticker is missing, returns -1 so the caller can alert the user.
    """
    try:
        conn = get_connection()
        c = conn.cursor()
        # fetch ticker first
        c.execute("SELECT ticker FROM ipo_filings WHERE id = ?", (filing_id,))
        row = c.fetchone()
        ticker = row[0] if row else None
        if not ticker:
            logger.warning(f"Cannot add filing {filing_id} to watchlist: missing ticker")
            return -1
        # check for existing active watchlist entry
        c.execute(
            "SELECT id FROM watchlist WHERE filing_id = ? AND status = 'watching'", (filing_id,)
        )
        existing = c.fetchone()
        if existing:
            return existing[0]
        # copy ticker/company_name from ipo_filings for convenience
        c.execute(
            """
            INSERT INTO watchlist(filing_id, ticker, company_name, entry_rationale, conviction_score)
            SELECT id, ticker, company_name, ?, ?
            FROM ipo_filings WHERE id = ?
            """,
            (entry_rationale, conviction_score, filing_id)
        )
        conn.commit()
        return c.lastrowid
    except Exception as e:
        logger.error(f"Failed to add filing {filing_id} to watchlist: {e}")
        conn.rollback()
        return -1
    finally:
        conn.close()


def set_expected_listing_date(filing_id: int, date_str: str) -> bool:
    """Record an expected listing date (YYYY-MM-DD) for an IPO filing.

    Returns True on success, False otherwise.
    """
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "UPDATE ipo_filings SET expected_listing_date = ? WHERE id = ?",
            (date_str, filing_id)
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to set expected listing date for {filing_id}: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# IPO calendar cache (separate DB to preserve historical scraping results)
# ---------------------------------------------------------------------------

CALENDAR_DB = "ipo_calendar.db"


def get_calendar_connection():
    conn = sqlite3.connect(CALENDAR_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_calendar_db():
    """Create the calendar cache table if it doesn't exist."""
    conn = get_calendar_connection()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS ipo_calendar (
            company_name TEXT PRIMARY KEY,
            expected_date TEXT,
            source TEXT,
            retrieved_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()


def lookup_calendar(company_name: str) -> str | None:
    """Return the cached expected date for a company, or None."""
    init_calendar_db()
    conn = get_calendar_connection()
    c = conn.cursor()
    c.execute("SELECT expected_date FROM ipo_calendar WHERE company_name = ?", (company_name,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def get_upcoming_listings(days: int = 30) -> list:
    """Return IPO filings whose expected listing date falls within the next `days` days.

    This is a convenience for building filters or alerts in the dashboard.
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT * FROM ipo_filings
        WHERE expected_listing_date IS NOT NULL
          AND date(expected_listing_date) BETWEEN date('now') AND date('now', '+' || ? || ' days')
        ORDER BY expected_listing_date ASC
        """,
        (days,)
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def save_calendar(company_name: str, expected_date: str, source: str = "scrape") -> None:
    """Insert or update a calendar entry."""
    init_calendar_db()
    conn = get_calendar_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO ipo_calendar(company_name, expected_date, source)
        VALUES(?,?,?)
        ON CONFLICT(company_name) DO UPDATE SET
            expected_date = excluded.expected_date,
            source = excluded.source,
            retrieved_at = datetime('now')
        """,
        (company_name, expected_date, source)
    )
    conn.commit()
    conn.close()


def remove_from_watchlist(watch_id: int) -> bool:
    """Marks a watchlist entry as removed (status='removed')."""
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("UPDATE watchlist SET status='removed', updated_at=datetime('now') WHERE id = ?", (watch_id,))
        conn.commit()
        return c.rowcount > 0
    except Exception as e:
        logger.error(f"Failed to remove watchlist id {watch_id}: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()



def get_filing_by_id(filing_id: int) -> dict:
    """Fetch a single IPO filing row by its primary key."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM ipo_filings WHERE id = ?", (filing_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else {}


def get_signals_for_ticker(ticker: str) -> list:
    """Return all signal score records for a given ticker ordered by date desc."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM signal_scores WHERE ticker = ? ORDER BY analysis_date DESC", (ticker,)
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_all_signals() -> list:
    """Return all entries in the signal_scores table."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM signal_scores ORDER BY analysis_date DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


if __name__ == "__main__":
    init_database()
