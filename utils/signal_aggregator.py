"""
SIGNAL AGGREGATOR
==================
Combines outputs from multiple models into a single ranked signal list.
Currently wraps ipo_scorer only — designed to add growth_predictor,
sector_rotation, india_ipo etc. without changing the agent/dashboard code.

Usage:
    from utils.signal_aggregator import get_top_signals
    signals = get_top_signals(min_score=70, markets=["US"], limit=20)
"""

import sqlite3, os
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Model weights — increase as more models are added and validated
MODEL_WEIGHTS = {
    "ipo_scorer":       1.00,   # live — Phase 5 complete
    "growth_predictor": 0.00,   # Phase 11 — not built yet
    "sector_rotation":  0.00,   # Phase 11 — not built yet
    "india_ipo":        0.00,   # Phase 12 — not built yet
}

def get_top_signals(
    min_score:   float = 70,
    markets:     list  = None,
    asset_types: list  = None,
    limit:       int   = 50,
) -> list[dict]:
    markets     = markets     or ["US"]
    asset_types = asset_types or ["ipo"]

    conn = sqlite3.connect(os.path.join(ROOT, "fintel.db"))
    conn.row_factory = sqlite3.Row

    # Discover which columns actually exist — never assume
    existing = {
        row[1] for row in
        conn.execute("PRAGMA table_info(ipo_filings)").fetchall()
    }

    # Build SELECT dynamically based on what exists
    base_cols = [
        "id", "company_name", "fintel_score", "verdict",
        "filing_date", "scored_at",
    ]
    optional_cols = [
        "regime", "tech_cycle", "beat_spy_prob", "expected_return",
        "winner_prob", "model_confidence", "model_used",
        "primary_sector", "market", "asset_type",
        "model_type", "data_source",
    ]
    select_cols = base_cols + [c for c in optional_cols if c in existing]
    select_sql  = ", ".join(select_cols)

    # Market + asset_type filters only if columns exist
    where_extra = ""
    params      = [min_score]

    if "market" in existing:
        placeholders = ",".join("?" for _ in markets)
        where_extra += f" AND COALESCE(market,'US') IN ({placeholders})"
        params.extend(markets)

    if "asset_type" in existing:
        placeholders = ",".join("?" for _ in asset_types)
        where_extra += f" AND COALESCE(asset_type,'ipo') IN ({placeholders})"
        params.extend(asset_types)

    params.append(limit)

    rows = conn.execute(f"""
        SELECT {select_sql}
        FROM ipo_filings
        WHERE fintel_score >= ?
          AND fintel_score IS NOT NULL
          {where_extra}
        ORDER BY fintel_score DESC
        LIMIT ?
    """, params).fetchall()

    conn.close()

    results = []
    for row in rows:
        r = dict(row)
        weight = MODEL_WEIGHTS.get(r.get("model_type", "ipo_scorer"), 1.0)
        r["weighted_score"] = round((r.get("fintel_score") or 0) * weight, 1)
        results.append(r)

    results.sort(key=lambda x: x["weighted_score"], reverse=True)
    return results


def get_signal_summary() -> dict:
    """Quick stats for dashboard Overview KPI cards."""
    try:
        conn = sqlite3.connect(os.path.join(ROOT, "fintel.db"))
        total    = conn.execute("SELECT COUNT(*) FROM ipo_filings WHERE fintel_score IS NOT NULL").fetchone()[0]
        strong   = conn.execute("SELECT COUNT(*) FROM ipo_filings WHERE verdict = 'strong_buy'").fetchone()[0]
        watching = conn.execute("SELECT COUNT(*) FROM ipo_filings WHERE verdict = 'watch'").fetchone()[0]
        conn.close()
        return {"total_scored": total, "strong_buy": strong, "watching": watching}
    except Exception:
        return {"total_scored": 0, "strong_buy": 0, "watching": 0}
