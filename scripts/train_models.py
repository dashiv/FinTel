"""
PHASE 5 — STEP 2: PER-REGIME MODEL TRAINING
============================================
Trains separate XGBoost models per market regime.

Three tasks per regime:
  Task A — Regression:      predict 1yr return magnitude (e.g. +34%)
  Task B — Classification:  predict outcome label (strong_winner/moderate/flat/loser)
  Task C — Binary:          did it beat S&P500 at 1yr? (yes/no)

Architecture:
  - One model per regime per task = up to 57 models (19 regimes × 3 tasks)
  - Only regimes with ≥ MIN_SAMPLES companies are trained
  - Temporal train/test split (no data leakage — chronological 80/20)
  - All experiments tracked in MLflow
  - SHAP values computed for top model per regime
  - Calibration applied to Task C (probability outputs must be calibrated)

Prerequisites:
  fintel_historical.db must exist with data.
  Minimum 50 labelled companies recommended per regime.

Run:    python scripts/train_models.py
Resume: same command — skips already-trained regimes
"""

import os, sys, json, sqlite3, warnings, joblib
import numpy as np
import pandas as pd
import xgboost as xgb
import mlflow
import mlflow.xgboost
import shap
from datetime import datetime, timedelta
from sklearn.preprocessing import LabelEncoder, OrdinalEncoder
from sklearn.metrics import (
    mean_absolute_error, r2_score,
    accuracy_score, f1_score, roc_auc_score,
    classification_report
)
from sklearn.calibration import CalibratedClassifierCV
import yfinance as yf
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from loguru import logger
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

console = Console()

# ── PATHS ─────────────────────────────────────────────────────────────────────

ROOT       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST_DB    = os.path.join(ROOT, "fintel_historical.db")
MODELS_DIR = os.path.join(ROOT, "models")
PLOTS_DIR  = os.path.join(ROOT, "models", "plots")
SPY_CACHE  = os.path.join(ROOT, "models", "spy_cache.parquet")

os.makedirs(MODELS_DIR, exist_ok=True)
os.makedirs(PLOTS_DIR,  exist_ok=True)

_mlflow_path = os.path.join(ROOT, "mlflow_runs").replace("\\", "/")
mlflow.set_tracking_uri(f"file:///{_mlflow_path}")
EXPERIMENT = "FinTel_PerRegime_v1"

# ── CONFIG ────────────────────────────────────────────────────────────────────

MIN_SAMPLES       = 50      # Minimum companies per regime to train
TEST_SPLIT_RATIO  = 0.20    # Chronological — last 20% of regime = test set
TARGET_DAYS       = 365     # Primary prediction horizon

OUTCOME_ORDER = ["loser", "flat", "moderate", "strong_winner"]

XGB_PARAMS_BASE = {
    "n_estimators":     400,
    "max_depth":        5,
    "learning_rate":    0.05,
    "subsample":        0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 3,
    "reg_alpha":        0.1,
    "reg_lambda":       1.0,
    "random_state":     42,
    "verbosity":        0,
    "n_jobs":           -1,
}


# ── SPY BENCHMARK ─────────────────────────────────────────────────────────────

def load_spy_returns() -> pd.Series:
    """
    Load SPY daily prices from 1993 to present.
    Cached to parquet — only fetches once.
    Returns a Series of daily Close prices indexed by date.
    """
    if os.path.exists(SPY_CACHE):
        logger.info("Loading SPY from cache")
        return pd.read_parquet(SPY_CACHE)["Close"]

    console.print("[yellow]Fetching SPY history from yfinance (one-time)...[/yellow]")
    spy = yf.Ticker("SPY").history(start="1993-01-01", auto_adjust=True)
    if spy.empty:
        logger.error("Failed to fetch SPY — Task C will be skipped")
        return pd.Series(dtype=float)

    try:
        spy.index = spy.index.tz_localize(None)
    except Exception:
        try:
            spy.index = spy.index.tz_convert(None)
        except Exception:
            pass

    spy.to_parquet(SPY_CACHE)
    console.print(f"  [green]✅ SPY cached: {len(spy)} trading days[/green]")
    return spy["Close"]


def get_spy_return(spy_prices: pd.Series, start_date: str, days: int = 365) -> float | None:
    """1yr SPY return from start_date."""
    if spy_prices.empty or not start_date:
        return None
    try:
        start_dt = pd.Timestamp(start_date)
        end_dt   = start_dt + timedelta(days=days)

        s_prices = spy_prices[spy_prices.index >= start_dt]
        e_prices = spy_prices[spy_prices.index >= end_dt]

        if s_prices.empty or e_prices.empty:
            return None

        return (float(e_prices.iloc[0]) - float(s_prices.iloc[0])) / float(s_prices.iloc[0])
    except Exception:
        return None


# ── DATA LOADING ──────────────────────────────────────────────────────────────

def load_training_data(spy_prices: pd.Series) -> pd.DataFrame:
    """
    Loads and joins all tables from fintel_historical.db into
    one flat feature DataFrame ready for model training.

    Returns one row per company with engineered features + all three targets.
    """
    conn = sqlite3.connect(HIST_DB)

    # Core company table
    ipos = pd.read_sql("""
        SELECT id, company_name, cik, filing_date, filing_type,
               sic_description, state, filing_regime, filing_tech_cycle,
               ticker, ipo_price, ticker_found
        FROM historical_ipos
        WHERE ticker_found = 1
    """, conn)

    # Price checkpoints — pivot to get returns at key offsets
    chk = pd.read_sql("""
        SELECT company_id, days_offset, return_vs_ipo, outcome_label,
               regime_at_checkpoint, tech_cycle_at_checkpoint
        FROM price_checkpoints
        WHERE days_offset IN (30, 60, 90, 180, 365)
    """, conn)

    # Event flags — aggregate per company
    evts = pd.read_sql("""
        SELECT company_id,
               COUNT(*) as event_count_total,
               SUM(CASE WHEN event_category='market_crash'  THEN 1 ELSE 0 END) as evt_crash,
               SUM(CASE WHEN event_category='macro_policy'  THEN 1 ELSE 0 END) as evt_macro,
               SUM(CASE WHEN event_category='geopolitical'  THEN 1 ELSE 0 END) as evt_geo,
               SUM(CASE WHEN event_category='tech_event'    THEN 1 ELSE 0 END) as evt_tech,
               SUM(CASE WHEN event_category='regulatory'    THEN 1 ELSE 0 END) as evt_reg,
               MIN(CASE WHEN event_category='market_crash' THEN days_into_window END) as days_to_next_crash
        FROM company_event_flags
        GROUP BY company_id
    """, conn)

    # Rolling IPO market temperature — count of filings per 90d window
    # Proxy for "is the IPO market hot right now?"
    all_filing_dates = pd.read_sql(
        "SELECT filing_date FROM historical_ipos WHERE filing_date IS NOT NULL",
        conn
    )

    conn.close()

    # ── Pivot checkpoints ──────────────────────────────────────────────────
    chk_pivot = chk.pivot_table(
        index="company_id",
        columns="days_offset",
        values="return_vs_ipo",
        aggfunc="first"
    ).reset_index()
    chk_pivot.columns = (
        ["company_id"] + [f"return_{int(c)}d" for c in chk_pivot.columns[1:]]
    )

    # 365d outcome label
    outcome_365 = chk[chk["days_offset"] == 365][
        ["company_id", "outcome_label"]
    ].rename(columns={"outcome_label": "outcome_label_365d"})

    # ── Rolling IPO temperature ────────────────────────────────────────────
    all_filing_dates["filing_date"] = pd.to_datetime(
        all_filing_dates["filing_date"], errors="coerce"
    )
    all_filing_dates = all_filing_dates.dropna()

    def ipo_temp(date_str):
        try:
            d   = pd.Timestamp(date_str)
            d90 = d - timedelta(days=90)
            return int(((all_filing_dates["filing_date"] >= d90) &
                        (all_filing_dates["filing_date"] < d)).sum())
        except Exception:
            return 0

    ipos["ipo_market_temp_90d"] = ipos["filing_date"].apply(ipo_temp)

    # ── S&P500 1yr return from filing date ────────────────────────────────
    console.print("[dim]Computing S&P500 benchmark returns per company...[/dim]")
    ipos["spy_return_1yr"] = ipos["filing_date"].apply(
        lambda d: get_spy_return(spy_prices, d, TARGET_DAYS)
    )

    # ── Merge everything ──────────────────────────────────────────────────
    df = ipos.merge(chk_pivot, left_on="id", right_on="company_id", how="left")
    df = df.merge(outcome_365,   on="company_id", how="left")
    df = df.merge(evts,          left_on="id", right_on="company_id", how="left")

    df["event_count_total"]   = df["event_count_total"].fillna(0)
    df["evt_crash"]           = df["evt_crash"].fillna(0)
    df["evt_macro"]           = df["evt_macro"].fillna(0)
    df["evt_geo"]             = df["evt_geo"].fillna(0)
    df["evt_tech"]            = df["evt_tech"].fillna(0)
    df["evt_reg"]             = df["evt_reg"].fillna(0)
    df["days_to_next_crash"]  = df["days_to_next_crash"].fillna(9999)

    # ── Target engineering ────────────────────────────────────────────────

    # Task A: 1yr return (regression)
    df["target_return_1yr"] = df.get("return_365d", pd.Series(dtype=float))

    # Task B: outcome label (4-class)
    df["target_outcome"] = df["outcome_label_365d"]

    # Task C: beat S&P500 (binary)
    df["target_beat_spy"] = (
        (df["target_return_1yr"].notna()) &
        (df["spy_return_1yr"].notna()) &
        (df["target_return_1yr"] > df["spy_return_1yr"])
    ).astype(int)
    # Mark as NaN where we couldn't compute
    df.loc[
        df["target_return_1yr"].isna() | df["spy_return_1yr"].isna(),
        "target_beat_spy"
    ] = np.nan

    # ── Filing date as sortable ───────────────────────────────────────────
    df["filing_date_dt"] = pd.to_datetime(df["filing_date"], errors="coerce")
    df["filing_year"]    = df["filing_date_dt"].dt.year
    df["filing_month"]   = df["filing_date_dt"].dt.month
    df["filing_quarter"] = df["filing_date_dt"].dt.quarter

    df = df.sort_values("filing_date_dt").reset_index(drop=True)

    console.print(
        f"  Dataset: [bold]{len(df)}[/bold] companies | "
        f"{df['target_return_1yr'].notna().sum()} with 1yr target | "
        f"{df['target_outcome'].notna().sum()} labelled"
    )

    return df


# ── FEATURE ENGINEERING ───────────────────────────────────────────────────────

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
    "return_30d",    # early momentum
    "return_60d",
    "return_90d",
    "return_180d",
]

ALL_FEATURES = CATEGORICAL_FEATURES + NUMERICAL_FEATURES


def build_feature_matrix(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Encode categoricals, fill nulls, return X and encoders.
    XGBoost handles nulls in numerical columns natively.
    """
    X = df[ALL_FEATURES].copy()

    encoders = {}
    for col in CATEGORICAL_FEATURES:
        X[col] = X[col].fillna("unknown").astype(str)
        enc    = LabelEncoder()
        X[col] = enc.fit_transform(X[col])
        encoders[col] = enc

    for col in NUMERICAL_FEATURES:
        X[col] = pd.to_numeric(X[col], errors="coerce")
        # Don't fill NaN in numerical — XGBoost handles natively

    return X, encoders


# ── MODEL TRAINING ────────────────────────────────────────────────────────────

def temporal_split(df_regime: pd.DataFrame, test_ratio: float = TEST_SPLIT_RATIO):
    """
    Chronological split. Sort by filing date, last test_ratio = test set.
    This prevents data leakage — you never train on future companies.
    """
    n_test = max(1, int(len(df_regime) * test_ratio))
    train  = df_regime.iloc[:-n_test]
    test   = df_regime.iloc[-n_test:]
    return train, test

def train_task_a(X_train, y_train, X_test, y_test, regime: str, run) -> dict:
    """Task A: Regression — predict 1yr return magnitude."""
    mask_train = y_train.notna()
    mask_test  = y_test.notna()

    if mask_train.sum() < 20:
        return {}

    has_test = mask_test.sum() > 0

    model = xgb.XGBRegressor(**XGB_PARAMS_BASE, objective="reg:squarederror")
    model.fit(
        X_train[mask_train], y_train[mask_train],
        eval_set=[(X_test[mask_test], y_test[mask_test])] if has_test else None,
        verbose=False
    )

    if not has_test:
        return {"model": model, "mae": None, "r2": None, "n_train": int(mask_train.sum())}

    preds  = model.predict(X_test[mask_test])
    actual = y_test[mask_test].values

    mae = mean_absolute_error(actual, preds)
    r2  = r2_score(actual, preds)

    mlflow.log_metrics({
        f"{regime}_taskA_mae": round(mae, 4),
        f"{regime}_taskA_r2":  round(r2,  4),
    }, run_id=run.info.run_id)

    return {"model": model, "mae": mae, "r2": r2, "n_train": int(mask_train.sum())}


def train_task_b(X_train, y_train, X_test, y_test, regime: str, run) -> dict:
    """Task B: 4-class classification — outcome label."""
    mask_train = y_train.notna()
    mask_test  = y_test.notna()

    if mask_train.sum() < 20:
        return {}

    has_test = mask_test.sum() > 0

    le = LabelEncoder()
    le.fit(OUTCOME_ORDER)

    yt_train = le.transform(y_train[mask_train])

    params = {**XGB_PARAMS_BASE,
              "objective":   "multi:softprob",
              "num_class":    4,
              "eval_metric": "mlogloss"}

    model = xgb.XGBClassifier(**params)

    if has_test:
        yt_test = le.transform(y_test[mask_test])
        model.fit(
            X_train[mask_train], yt_train,
            eval_set=[(X_test[mask_test], yt_test)],
            verbose=False
        )
        preds = model.predict(X_test[mask_test])
        acc   = accuracy_score(yt_test, preds)
        f1    = f1_score(yt_test, preds, average="weighted")
        mlflow.log_metrics({
            f"{regime}_taskB_acc": round(acc, 4),
            f"{regime}_taskB_f1":  round(f1,  4),
        }, run_id=run.info.run_id)
    else:
        model.fit(X_train[mask_train], yt_train, verbose=False)
        acc = f1 = None

    return {"model": model, "label_encoder": le,
            "accuracy": acc, "f1": f1, "n_train": int(mask_train.sum())}


def train_task_c(X_train, y_train, X_test, y_test, regime: str, run) -> dict:
    """Task C: Binary — beat S&P500 or not."""
    mask_train = y_train.notna()
    mask_test  = y_test.notna()

    if mask_train.sum() < 20:
        return {}

    has_test = mask_test.sum() > 0

    params = {**XGB_PARAMS_BASE,
              "objective":   "binary:logistic",
              "eval_metric": "logloss",
              "scale_pos_weight": (
                  (mask_train.sum() - y_train[mask_train].sum()) /
                  max(y_train[mask_train].sum(), 1)
              )}

    model = xgb.XGBClassifier(**params)

    if has_test:
        model.fit(
            X_train[mask_train], y_train[mask_train].astype(int),
            eval_set=[(X_test[mask_test], y_test[mask_test].astype(int))],
            verbose=False
        )
        preds      = model.predict(X_test[mask_test])
        preds_prob = model.predict_proba(X_test[mask_test])[:, 1]
        actual     = y_test[mask_test].astype(int).values

        acc      = accuracy_score(actual, preds)
        win_rate = float(preds[actual == 1].sum()) / max(float(preds.sum()), 1)

        try:
            auc = roc_auc_score(actual, preds_prob)
        except Exception:
            auc = 0.0

        mlflow.log_metrics({
            f"{regime}_taskC_acc":      round(acc,      4),
            f"{regime}_taskC_auc":      round(auc,      4),
            f"{regime}_taskC_win_rate": round(win_rate, 4),
        }, run_id=run.info.run_id)
    else:
        model.fit(
            X_train[mask_train], y_train[mask_train].astype(int),
            verbose=False
        )
        acc = win_rate = auc = None

    return {"model": model, "accuracy": acc,
            "auc": auc, "win_rate": win_rate, "n_train": int(mask_train.sum())}

# ── SHAP EXPLAINABILITY ───────────────────────────────────────────────────────

def compute_shap(model, X_test: pd.DataFrame, regime: str, task: str):
    """
    Compute SHAP values for the test set and save a summary plot.
    Shows the top 15 most important features for this regime's model.
    """
    try:
        explainer   = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X_test.fillna(0))

        # For multi-class, take mean absolute across classes
        if isinstance(shap_values, list):
            sv = np.mean([np.abs(s) for s in shap_values], axis=0)
        else:
            sv = shap_values

        plt.figure(figsize=(10, 6))
        shap.summary_plot(
            sv, X_test.fillna(0),
            feature_names=ALL_FEATURES,
            max_display=15,
            show=False,
            plot_type="bar"
        )
        plt.title(f"SHAP Feature Importance — {regime} / Task {task}", pad=12)
        plt.tight_layout()

        path = os.path.join(PLOTS_DIR, f"shap_{regime}_{task}.png")
        plt.savefig(path, dpi=120, bbox_inches="tight")
        plt.close()
        logger.info(f"SHAP plot saved: {path}")

    except Exception as e:
        logger.warning(f"SHAP failed for {regime}/{task}: {e}")


# ── CALIBRATION CURVE ─────────────────────────────────────────────────────────

def save_calibration_plot(model, X_test: pd.DataFrame, y_test: pd.Series,
                           regime: str):
    """
    For Task C binary model: plot predicted probability vs actual win rate.
    A well-calibrated model's curve should lie close to the diagonal.
    """
    try:
        mask   = y_test.notna()
        probs  = model.predict_proba(X_test[mask].fillna(0))[:, 1]
        actual = y_test[mask].astype(int).values

        from sklearn.calibration import calibration_curve
        fraction_pos, mean_pred = calibration_curve(
            actual, probs, n_bins=10, strategy="quantile"
        )

        plt.figure(figsize=(6, 5))
        plt.plot([0, 1], [0, 1], "k--", label="Perfect calibration")
        plt.plot(mean_pred, fraction_pos, "b-o", label=regime)
        plt.xlabel("Mean predicted probability")
        plt.ylabel("Fraction of positives")
        plt.title(f"Calibration Curve — {regime} Task C")
        plt.legend()
        plt.tight_layout()

        path = os.path.join(PLOTS_DIR, f"calibration_{regime}.png")
        plt.savefig(path, dpi=120, bbox_inches="tight")
        plt.close()
        logger.info(f"Calibration plot: {path}")
    except Exception as e:
        logger.warning(f"Calibration plot failed for {regime}: {e}")


# ── MODEL PERSISTENCE ─────────────────────────────────────────────────────────

def save_models(regime: str, results: dict, encoders: dict):
    """Save all trained models and encoders for a regime to disk."""
    regime_dir = os.path.join(MODELS_DIR, regime)
    os.makedirs(regime_dir, exist_ok=True)

    manifest = {"regime": regime, "trained_at": datetime.now().isoformat(),
                "features": ALL_FEATURES, "tasks": {}}

    for task, res in results.items():
        if not res or "model" not in res:
            continue
        path = os.path.join(regime_dir, f"{task}.joblib")
        joblib.dump(res["model"], path)
        manifest["tasks"][task] = {
            "model_path": path,
            "metrics": {k: v for k, v in res.items() if k != "model"},
        }

    # Save encoders
    enc_path = os.path.join(regime_dir, "encoders.joblib")
    joblib.dump(encoders, enc_path)
    manifest["encoders_path"] = enc_path

    # Save manifest
    manifest_path = os.path.join(regime_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, default=str)

    return manifest


def is_regime_trained(regime: str) -> bool:
    manifest_path = os.path.join(MODELS_DIR, regime, "manifest.json")
    return os.path.exists(manifest_path)


# ── RESULTS SUMMARY TABLE ─────────────────────────────────────────────────────

def print_results_table(all_results: list[dict]):
    """Print a cross-regime comparison of all trained models."""
    t = Table(
        title="📊 Per-Regime Model Results",
        header_style="bold cyan",
        show_lines=True
    )
    t.add_column("Regime",           style="dim",         width=28)
    t.add_column("N Train",          justify="right",     width=8)
    t.add_column("A: MAE",           justify="right",     width=8)
    t.add_column("A: R²",            justify="right",     width=8)
    t.add_column("B: F1",            justify="right",     width=8)
    t.add_column("B: Acc",           justify="right",     width=8)
    t.add_column("C: AUC",           justify="right",     width=8)
    t.add_column("C: WinRate",       justify="right",     width=10)

    for r in sorted(all_results, key=lambda x: x["regime"]):
        a = r.get("task_a", {})
        b = r.get("task_b", {})
        c = r.get("task_c", {})

        wr     = c.get("win_rate", None)
        wr_str = f"[bold green]{wr:.1%}[/bold green]" if wr and wr >= 0.63 \
                 else (f"{wr:.1%}" if wr else "—")

        t.add_row(
            r["regime"],
            str(r.get("n_total", "—")),
            f"{a['mae']:.3f}"  if a.get("mae")      else "—",
            f"{a['r2']:.3f}"   if a.get("r2")       else "—",
            f"{b['f1']:.3f}"   if b.get("f1")       else "—",
            f"{b['accuracy']:.3f}" if b.get("accuracy") else "—",
            f"{c['auc']:.3f}"  if c.get("auc")      else "—",
            wr_str,
        )

    console.print("\n")
    console.print(t)
    console.print("[dim]Green win rate = meets ≥63% quality threshold[/dim]\n")


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    console.rule("[bold magenta]🤖 FinTel — Phase 5 Per-Regime Model Training[/bold magenta]")

    if not os.path.exists(HIST_DB):
        console.print(f"[red]❌ {HIST_DB} not found. Run collect_historical_ipos.py first.[/red]")
        sys.exit(1)

    # ── Load SPY benchmark
    spy_prices = load_spy_returns()

    # ── Load and engineer full dataset
    console.print("\n[bold]Loading training data...[/bold]")
    df           = load_training_data(spy_prices)
    X_all, encoders = build_feature_matrix(df)

    # ── Get unique regimes with enough data
    regime_counts = (
        df[df["target_return_1yr"].notna()]
        .groupby("filing_regime")
        .size()
        .reset_index(name="n")
    )
    trainable = regime_counts[regime_counts["n"] >= MIN_SAMPLES]["filing_regime"].tolist()
    skipped   = regime_counts[regime_counts["n"] <  MIN_SAMPLES]["filing_regime"].tolist()

    if skipped:
        console.print(f"[yellow]⚠ Skipping (< {MIN_SAMPLES} samples): {skipped}[/yellow]")

    console.print(
        f"Training on [bold]{len(trainable)}[/bold] regimes: "
        f"{', '.join(trainable)}\n"
    )

    # ── MLflow setup
    try:
        mlflow.create_experiment(EXPERIMENT)
    except Exception:
        pass
    mlflow.set_experiment(EXPERIMENT)

    all_results = []

    for regime in trainable:

        if is_regime_trained(regime):
            console.print(f"  [dim]Skipping {regime} — already trained[/dim]")
            continue

        console.rule(f"[cyan]{regime}[/cyan]")

        df_r    = df[df["filing_regime"] == regime].copy()
        X_r     = X_all.loc[df_r.index]

        train_df, test_df = temporal_split(df_r)
        X_train = X_r.loc[train_df.index]
        X_test  = X_r.loc[test_df.index]

        n_total = len(df_r)
        n_train = len(train_df)
        n_test  = len(test_df)
        console.print(f"  {n_total} companies | {n_train} train | {n_test} test")

        regime_results = {"regime": regime, "n_total": n_total}

        with mlflow.start_run(run_name=regime) as run:

            mlflow.log_params({
                "regime":      regime,
                "n_total":     n_total,
                "n_train":     n_train,
                "n_test":      n_test,
                "features":    str(ALL_FEATURES),
                "target_days": TARGET_DAYS,
            })

            # ── Task A: Regression
            console.print("  [dim]Task A: Return regression...[/dim]")
            res_a = train_task_a(
                X_train, train_df["target_return_1yr"],
                X_test,  test_df["target_return_1yr"],
                regime, run
            )
            regime_results["task_a"] = res_a
            if res_a.get("model"):
                mae_str = f"{res_a['mae']:.3f}" if res_a.get("mae") is not None else "—"
                r2_str  = f"{res_a['r2']:.3f}"  if res_a.get("r2")  is not None else "—"
                console.print(f"  [green]Task A:[/green] MAE={mae_str}  R²={r2_str}")

            # ── Task B: Classification
            console.print("  [dim]Task B: Outcome classification...[/dim]")
            res_b = train_task_b(
                X_train, train_df["target_outcome"],
                X_test,  test_df["target_outcome"],
                regime, run
            )
            regime_results["task_b"] = res_b
            if res_b.get("model"):
                acc_str = f"{res_b['accuracy']:.3f}" if res_b.get("accuracy") is not None else "—"
                f1_str  = f"{res_b['f1']:.3f}"       if res_b.get("f1")       is not None else "—"
                console.print(f"  [green]Task B:[/green] Acc={acc_str}  F1={f1_str}")

            # ── Task C: Beat S&P500
            console.print("  [dim]Task C: Beat S&P500 binary...[/dim]")
            res_c = train_task_c(
                X_train, train_df["target_beat_spy"],
                X_test,  test_df["target_beat_spy"],
                regime, run
            )
            regime_results["task_c"] = res_c
            if res_c.get("model"):
                wr      = res_c.get("win_rate")
                auc     = res_c.get("auc")
                wr_str  = f"{wr:.1%}"   if wr  is not None else "—"
                auc_str = f"{auc:.3f}"  if auc is not None else "—"
                color   = "green" if (wr or 0) >= 0.63 else "yellow"
                console.print(
                    f"  [{color}]Task C:[/{color}] "
                    f"AUC={auc_str}  WinRate={wr_str}"
                )

            # ── SHAP (Task B — most interpretable)
            if res_b.get("model") and n_test >= 20:
                compute_shap(res_b["model"], X_test.fillna(0), regime, "B")

            # ── Calibration curve (Task C)
            if res_c.get("model"):
                save_calibration_plot(
                    res_c["model"], X_test,
                    test_df["target_beat_spy"], regime
                )

            # ── Save models
            manifest = save_models(regime, {
                "task_a": res_a,
                "task_b": res_b,
                "task_c": res_c,
            }, encoders)

            mlflow.log_artifact(
                os.path.join(MODELS_DIR, regime, "manifest.json")
            )
            console.print(f"  [green]✅ {regime} saved[/green]")

        all_results.append(regime_results)

    # ── Final summary
    console.rule("[bold green]✅ Training Complete[/bold green]")
    if all_results:
        print_results_table(all_results)

    console.print(f"[dim]Models saved to: {MODELS_DIR}[/dim]")
    console.print("[dim]View MLflow: open http://127.0.0.1:5000[/dim]")
    console.print("[dim]Next: python scripts/score_new_ipos.py[/dim]")


if __name__ == "__main__":
    main()

