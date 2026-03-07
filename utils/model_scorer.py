"""
MODEL SCORER — Inference Layer
================================
Loads trained per-regime models and scores any new company.
Called by score_new_ipos.py and (in Phase 6) the live IBKR agent.

Returns a FinTel Score (0–100) combining all three task outputs:
  Task A (regression)     → expected return magnitude
  Task B (classification) → outcome label probability
  Task C (binary)         → probability of beating S&P500

Usage:
    from utils.model_scorer import score_company
    result = score_company(company_dict)
    print(result["fintel_score"], result["regime"], result["verdict"])
"""

import os, sys, json, joblib, warnings
import numpy as np
import pandas as pd
from datetime import datetime

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.events_db import get_regime, get_tech_cycle, get_events_in_window

ROOT       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(ROOT, "models")

# ── FEATURE DEFINITION (must match train_models.py exactly) ───────────────────

CATEGORICAL_FEATURES = [
    "filing_type",
    "state",
    "sic_description",
    "filing_tech_cycle",
]

NUMERICAL_FEATURES = [
    "ipo_price",
    "ipo_market_temp_90d",
    "filing_year",
    "filing_month",
    "filing_quarter",
    "event_count_total",
    "evt_crash",
    "evt_macro",
    "evt_geo",
    "evt_tech",
    "evt_reg",
    "days_to_next_crash",
    "return_30d",
    "return_60d",
    "return_90d",
    "return_180d",
]

ALL_FEATURES = CATEGORICAL_FEATURES + NUMERICAL_FEATURES

# Composite score weights — tunable
SCORE_WEIGHTS = {
    "task_c_beat_spy_prob": 0.55,    # Most important: will it beat market?
    "task_b_winner_prob":   0.35,    # Outcome class probability
    "task_a_return_norm":   0.10,    # Magnitude of expected return
}

OUTCOME_ORDER  = ["loser", "flat", "moderate", "strong_winner"]
WINNER_IDX     = OUTCOME_ORDER.index("strong_winner")
MODERATE_IDX   = OUTCOME_ORDER.index("moderate")


# ── MODEL LOADER (cached in memory) ──────────────────────────────────────────

_model_cache: dict = {}

def _load_regime_models(regime: str) -> dict | None:
    """Load and cache all three task models + encoders for a regime."""
    if regime in _model_cache:
        return _model_cache[regime]

    regime_dir    = os.path.join(MODELS_DIR, regime)
    manifest_path = os.path.join(regime_dir, "manifest.json")

    if not os.path.exists(manifest_path):
        return None

    with open(manifest_path) as f:
        manifest = json.load(f)

    bundle = {"manifest": manifest}

    for task in ["task_a", "task_b", "task_c"]:
        task_info = manifest.get("tasks", {}).get(task)
        if task_info and os.path.exists(task_info.get("model_path", "")):
            bundle[task] = joblib.load(task_info["model_path"])

    enc_path = manifest.get("encoders_path")
    if enc_path and os.path.exists(enc_path):
        bundle["encoders"] = joblib.load(enc_path)

    _model_cache[regime] = bundle
    return bundle


def get_available_regimes() -> list[str]:
    """Return list of regimes that have trained models."""
    if not os.path.exists(MODELS_DIR):
        return []
    return [
        d for d in os.listdir(MODELS_DIR)
        if os.path.exists(os.path.join(MODELS_DIR, d, "manifest.json"))
    ]


# ── FEATURE BUILDER ──────────────────────────────────────────────────────────

def build_feature_row(company: dict) -> pd.DataFrame:
    """
    Convert a raw company dict (from DB or SEC EDGAR) into
    a single-row feature DataFrame ready for model inference.

    Handles missing values gracefully — XGBoost tolerates NaN in numerics.
    """
    filing_date = company.get("filing_date", "")
    filing_dt   = None
    try:
        filing_dt = datetime.strptime(filing_date[:10], "%Y-%m-%d")
    except Exception:
        pass

    # Time features
    year    = filing_dt.year    if filing_dt else np.nan
    month   = filing_dt.month   if filing_dt else np.nan
    quarter = (filing_dt.month - 1) // 3 + 1 if filing_dt else np.nan

    # Event context from fintel_events.db
    event_count = evt_crash = evt_macro = evt_geo = evt_tech = evt_reg = 0
    days_to_crash = 9999
    if filing_date:
        from datetime import timedelta
        window_end = (filing_dt + timedelta(days=365)).strftime("%Y-%m-%d") if filing_dt else filing_date
        events = get_events_in_window(filing_date, window_end)
        event_count = len(events)
        for ev in events:
            cat = ev.get("category", "")
            if cat == "market_crash":
                evt_crash += 1
                if filing_dt:
                    try:
                        ev_dt = datetime.strptime(ev["event_date"], "%Y-%m-%d")
                        days  = (ev_dt - filing_dt).days
                        if days >= 0:
                            days_to_crash = min(days_to_crash, days)
                    except Exception:
                        pass
            elif cat == "macro_policy": evt_macro += 1
            elif cat == "geopolitical": evt_geo   += 1
            elif cat == "tech_event":   evt_tech  += 1
            elif cat == "regulatory":   evt_reg   += 1

    tech_cycle = get_tech_cycle(filing_date)

    row = {
        # Categoricals
        "filing_type":      company.get("filing_type", "S-1"),
        "state":            company.get("state") or company.get("state_of_incorporation", "unknown"),
        "sic_description":  company.get("sic_description", "unknown"),
        "filing_tech_cycle": tech_cycle,

        # Numericals
        "ipo_price":          company.get("ipo_price") or np.nan,
        "ipo_market_temp_90d":company.get("ipo_market_temp_90d", 0),
        "filing_year":        year,
        "filing_month":       month,
        "filing_quarter":     quarter,
        "event_count_total":  event_count,
        "evt_crash":          evt_crash,
        "evt_macro":          evt_macro,
        "evt_geo":            evt_geo,
        "evt_tech":           evt_tech,
        "evt_reg":            evt_reg,
        "days_to_next_crash": days_to_crash,
        "return_30d":         company.get("return_30d", np.nan),
        "return_60d":         company.get("return_60d", np.nan),
        "return_90d":         company.get("return_90d", np.nan),
        "return_180d":        company.get("return_180d", np.nan),
    }
    return pd.DataFrame([row])[ALL_FEATURES]


def _encode_row(X: pd.DataFrame, encoders: dict) -> pd.DataFrame:
    """Apply saved LabelEncoders to categorical columns."""
    X = X.copy()
    for col in CATEGORICAL_FEATURES:
        enc = encoders.get(col)
        if enc is None:
            X[col] = 0
            continue
        val = str(X[col].iloc[0])
        if val not in enc.classes_:
            val = "unknown" if "unknown" in enc.classes_ else enc.classes_[0]
        X[col] = enc.transform([val])[0]
    for col in NUMERICAL_FEATURES:
        X[col] = pd.to_numeric(X[col], errors="coerce")
    return X


# ── COMPOSITE SCORE BUILDER ──────────────────────────────────────────────────

def _build_composite_score(
    task_a_return:     float | None,
    task_b_probs:      np.ndarray | None,
    task_c_beat_prob:  float | None,
) -> dict:
    """
    Combine three model outputs into a single FinTel Score (0–100).

    Component logic:
      - Task C (beat S&P prob): 0–1 → scaled to 0–100
      - Task B (winner class prob): P(strong_winner) + 0.5*P(moderate)
      - Task A (return): sigmoid-normalised around 0%–50% return range

    Weighted sum then clipped to 0–100.
    """

    # Task C component
    c_score = float(task_c_beat_prob) * 100 if task_c_beat_prob is not None else 50.0

    # Task B component — weight winner + moderate
    b_score = 50.0
    winner_prob = moderate_prob = 0.0
    if task_b_probs is not None and len(task_b_probs) == 4:
        winner_prob   = float(task_b_probs[WINNER_IDX])
        moderate_prob = float(task_b_probs[MODERATE_IDX])
        b_score = (winner_prob * 100) + (moderate_prob * 50)
        b_score = min(100.0, b_score)

    # Task A component — sigmoid normalisation
    a_score = 50.0
    if task_a_return is not None:
        r = float(task_a_return)
        # Map: -100% → 0, 0% → 40, +30% → 65, +50% → 80, +100% → 95
        a_score = 100 / (1 + np.exp(-5 * (r - 0.15)))
        a_score = float(np.clip(a_score * 100, 0, 100))

    # Weighted composite
    fintel_score = (
        SCORE_WEIGHTS["task_c_beat_spy_prob"] * c_score +
        SCORE_WEIGHTS["task_b_winner_prob"]   * b_score +
        SCORE_WEIGHTS["task_a_return_norm"]   * a_score
    )
    fintel_score = float(np.clip(fintel_score, 0, 100))

    # Verdict label
    if fintel_score >= 75:
        verdict = "strong_buy"
    elif fintel_score >= 60:
        verdict = "watch"
    elif fintel_score >= 45:
        verdict = "neutral"
    else:
        verdict = "avoid"

    return {
        "fintel_score":    round(fintel_score, 1),
        "verdict":         verdict,
        "c_score":         round(c_score, 1),
        "b_score":         round(b_score, 1),
        "a_score":         round(a_score, 1),
        "beat_spy_prob":   round(task_c_beat_prob * 100, 1) if task_c_beat_prob else None,
        "winner_prob":     round(winner_prob * 100, 1),
        "moderate_prob":   round(moderate_prob * 100, 1),
        "expected_return": round(task_a_return * 100, 1) if task_a_return else None,
    }


# ── MAIN PUBLIC FUNCTION ──────────────────────────────────────────────────────

def score_company(company: dict, override_regime: str = None) -> dict:
    """
    Score a single company dict and return full scoring breakdown.

    Args:
        company:          dict with at minimum 'filing_date', 'filing_type',
                          'sic_description', 'state'. Richer = better scores.
        override_regime:  force a specific regime (for backtesting / what-if)

    Returns:
        dict with keys:
          fintel_score    — 0 to 100
          verdict         — strong_buy / watch / neutral / avoid
          regime          — market regime at filing date
          tech_cycle      — tech cycle at filing date
          model_used      — which regime's model was used
          beat_spy_prob   — probability of beating S&P500 (%)
          expected_return — Task A point estimate (%)
          winner_prob     — probability of strong_winner outcome (%)
          confidence      — how confident we are (based on training set size)
          scored_at       — timestamp
          components      — c_score, b_score, a_score breakdown
    """

    filing_date  = company.get("filing_date", "")
    regime       = override_regime or get_regime(filing_date)
    tech_cycle   = get_tech_cycle(filing_date)
    available    = get_available_regimes()

    # Model selection: exact match → fallback to most recent trained regime
    BEST_FALLBACK = "qe3_secular_bull"

    model_used = regime if regime in available else (
    BEST_FALLBACK if BEST_FALLBACK in available else
    available[-1] if available else None
)

    if not model_used:
        return {
            "fintel_score":    None,
            "verdict":         "no_model",
            "regime":          regime,
            "tech_cycle":      tech_cycle,
            "model_used":      None,
            "error":           "No trained models found. Run train_models.py first.",
            "scored_at":       datetime.now().isoformat(),
        }

    bundle = _load_regime_models(model_used)
    if not bundle:
        return {
            "fintel_score": None,
            "verdict":      "model_load_error",
            "regime":       regime,
            "tech_cycle":   tech_cycle,
            "model_used":   model_used,
            "scored_at":    datetime.now().isoformat(),
        }

    # Build feature row
    X_raw = build_feature_row(company)
    X     = _encode_row(X_raw, bundle.get("encoders", {}))

    # Run Task A (regression)
    task_a_return = None
    if "task_a" in bundle:
        try:
            task_a_return = float(bundle["task_a"].predict(X)[0])
        except Exception:
            pass

    # Run Task B (4-class classification)
    task_b_probs = None
    if "task_b" in bundle:
        try:
            task_b_probs = bundle["task_b"].predict_proba(X)[0]
        except Exception:
            pass

    # Run Task C (binary beat-SPY)
    task_c_prob = None
    if "task_c" in bundle:
        try:
            task_c_prob = float(bundle["task_c"].predict_proba(X)[0][1])
        except Exception:
            pass

    # Build composite
    result = _build_composite_score(task_a_return, task_b_probs, task_c_prob)

    # Training set size → confidence
    n_train = bundle["manifest"].get("tasks", {}).get(
        "task_c", {}
    ).get("metrics", {}).get("n_train", 0)
    confidence = "high" if n_train >= 200 else "medium" if n_train >= 80 else "low"

    result.update({
        "regime":       regime,
        "tech_cycle":   tech_cycle,
        "model_used":   model_used,
        "confidence":   confidence,
        "n_train":      n_train,
        "fallback_used": model_used != regime,
        "scored_at":    datetime.now().isoformat(),
    })
    return result


if __name__ == "__main__":
    # Quick smoke test
    from rich.console import Console
    from rich.table import Table
    console = Console()

    test = {
        "company_name":   "TestCo Inc",
        "filing_date":    "2024-06-01",
        "filing_type":    "S-1",
        "sic_description":"Software",
        "state":          "DE",
        "ipo_price":      None,
    }

    res = score_company(test)
    t   = Table(title="🧪 Scorer Smoke Test", header_style="bold cyan")
    t.add_column("Field",  style="dim")
    t.add_column("Value",  style="bold")
    for k, v in res.items():
        t.add_row(str(k), str(v))
    console.print(t)
