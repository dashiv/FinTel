"""
USER INTELLIGENCE INPUT LAYER
================================
Allows the user to suggest stocks/companies directly to the FinTel engine.
The agent evaluates them using the same scoring pipeline as auto-discovered IPOs,
then decides whether to add to watchlist or flag for trading.

This is the human-in-the-loop intelligence layer — the user's intuition
feeds the model, not the other way around.

Usage from dashboard (Phase 6):
    suggest_company("NVDA", notes="AI infrastructure play, undervalued vs peers")
    → FinTel scores it → if ≥ 75 → adds to watchlist → agent considers buying

Usage from CLI:
    python utils/user_watchlist_intel.py --ticker NVDA --notes "AI play"
"""

import sqlite3, os, sys, argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ensure_user_suggestions_table():
    """Create user_suggestions table if it doesn't exist."""
    conn = sqlite3.connect(os.path.join(ROOT, "fintel.db"))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_suggestions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker          TEXT,
            company_name    TEXT,
            user_notes      TEXT,
            market          TEXT DEFAULT 'US',
            asset_type      TEXT DEFAULT 'stock',
            suggested_at    TEXT,
            fintel_score    REAL,
            verdict         TEXT,
            agent_action    TEXT,   -- 'watchlist' | 'skip' | 'buy_flagged' | 'pending'
            scored_at       TEXT,
            outcome         TEXT    -- filled in by feedback engine later
        )
    """)
    conn.commit()
    conn.close()


def suggest_company(
    ticker:       str,
    company_name: str = None,
    notes:        str = "",
    market:       str = "US",
    asset_type:   str = "stock",
) -> dict:
    """
    User suggests a company. FinTel scores it and decides what to do.

    Returns the scoring result dict.
    """
    ensure_user_suggestions_table()

    # Enrich with yfinance data
    company_dict = {
        "ticker":       ticker.upper(),
        "company_name": company_name or ticker.upper(),
        "filing_date":  datetime.now().strftime("%Y-%m-%d"),
        "filing_type":  "user_suggestion",
        "market":       market,
        "asset_type":   asset_type,
        "user_notes":   notes,
    }

    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        company_dict["company_name"]   = info.get("longName") or company_name or ticker
        company_dict["sic_description"] = info.get("industry", "unknown")
        company_dict["state"]           = info.get("state", "unknown")
        company_dict["ipo_price"]       = info.get("regularMarketPrice")
        company_dict["primary_sector"]  = info.get("sector", "unknown")
    except Exception:
        pass

    # Score it
    try:
        from utils.model_scorer import score_company
        result = score_company(company_dict)
    except Exception as e:
        result = {"fintel_score": None, "verdict": "error", "error": str(e)}

    # Decide agent action
    score   = result.get("fintel_score") or 0
    verdict = result.get("verdict", "neutral")
    if score >= 75:
        agent_action = "watchlist"
    elif score >= 60:
        agent_action = "monitor"
    else:
        agent_action = "skip"

    # Save suggestion
    conn = sqlite3.connect(os.path.join(ROOT, "fintel.db"))
    conn.execute("""
        INSERT INTO user_suggestions
        (ticker, company_name, user_notes, market, asset_type,
         suggested_at, fintel_score, verdict, agent_action, scored_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
        ticker.upper(),
        company_dict["company_name"],
        notes, market, asset_type,
        datetime.now().isoformat(),
        result.get("fintel_score"),
        verdict, agent_action,
        result.get("scored_at"),
    ))
    conn.commit()
    conn.close()

    result["agent_action"]  = agent_action
    result["ticker"]        = ticker.upper()
    result["company_name"]  = company_dict["company_name"]
    return result


def get_user_suggestions(min_score: float = 0) -> list[dict]:
    """Retrieve all user suggestions for dashboard display."""
    ensure_user_suggestions_table()
    conn = sqlite3.connect(os.path.join(ROOT, "fintel.db"))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT * FROM user_suggestions
        WHERE fintel_score >= ? OR fintel_score IS NULL
        ORDER BY suggested_at DESC
    """, (min_score,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Suggest a stock to FinTel")
    parser.add_argument("--ticker",  required=True, help="Stock ticker e.g. NVDA")
    parser.add_argument("--name",    default=None,  help="Company name (optional)")
    parser.add_argument("--notes",   default="",    help="Your reasoning")
    parser.add_argument("--market",  default="US",  help="Market: US, EU, IN")
    args = parser.parse_args()

    print(f"\n🧠 Scoring {args.ticker}...")
    result = suggest_company(args.ticker, args.name, args.notes, args.market)

    print(f"\n{'='*50}")
    print(f"Company:      {result.get('company_name')}")
    print(f"FinTel Score: {result.get('fintel_score')}")
    print(f"Verdict:      {result.get('verdict')}")
    print(f"Beat SPY Prob:{result.get('beat_spy_prob')}%")
    print(f"Agent Action: {result.get('agent_action').upper()}")
    print(f"{'='*50}\n")
