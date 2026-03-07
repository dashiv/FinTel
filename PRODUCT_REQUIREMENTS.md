# FinTel — Master Product Requirements Document
**Version:** 2.1  
**Last Updated:** 2026-03-04  
**Author:** Shivam Datta  
**Status:** Living document — update as features are completed

---
## WHAT IS FINTEL

FinTel is a local, AI-powered financial intelligence platform built to:

1. **Find and score** new IPO filings before the market prices them efficiently
2. **Predict** post-IPO stock performance using ML models trained across the full history of US IPOs — segmented by market regime, retrained iteratively with maximum lookback, and weighted by temporal relevance so recent market conditions inform predictions more heavily than outdated ones
3. **Identify** high-probability investment opportunities with rigorous statistical backing
4. **Execute trades** automatically via Interactive Brokers API (with strict human-in-the-loop guardrails)
5. **Track real-time** public stocks and correlate with breaking news, geopolitics, and macro trends
6. **Self-improve continuously** via a built-in feedback engine that measures every prediction against real outcomes, recalibrates models automatically, and increases efficiency and profitability over time
7. **Scale** — as the feedback loop matures and model accuracy is proven, the platform is designed to scale from personal tool → signal subscription SaaS → fully automated quantitative system
8. Operate entirely on a local machine — zero cloud costs, zero subscriptions

> **The feedback engine is not a feature — it is a core design principle.**
> Every prediction FinTel makes is stored with a timestamp and confidence score. Real outcomes are measured at 30, 90, 180, and 365 days. The delta between prediction and reality is the engine's fuel — it drives automatic model retraining, error margin reduction, and continuous improvement of both efficiency (accuracy) and profitability (risk-adjusted returns). The system is designed to get measurably better every month.

**Primary purpose:** Learn AI engineering through real, production-grade code
**Secondary purpose:** Personal trading tool (€5K capital, Luxembourg 183-day tax optimised) — self-improving model means edge compounds over time
**Tertiary purpose:** Potential SaaS product — signal research subscriptions, with the feedback engine as the core differentiator vs static screeners

---

## TECHNOLOGY STACK

### Current (Zero-Cost Local)
| Component | Technology | Purpose |
|---|---|---|
| Language | Python 3.14 | Everything |
| Local AI | Ollama — mistral:7b, deepseek-r1:7b | Classification + analysis |
| Stock data | yfinance | Price history + real-time quotes |
| IPO data | SEC EDGAR API (free) | S-1/F-1 filing discovery |
| News | Google News RSS / feedparser | Sentiment input |
| Database | SQLite (built into Python) | Local data store — 3 DBs (fintel, historical, events) |
| Dashboard | Streamlit + Plotly | Visualisation — v3.0 live |
| Technical indicators | ta library | RSI, MACD, SMA, Bollinger Bands |
| Scheduling | APScheduler (CronTrigger, CET) | Automated daily runs |
| Experiment tracking | MLflow | Model performance logging |
| ML models | XGBoost | Per-regime prediction models |
| Remote access | Tailscale | Secure VPN — dashboard on iPhone from anywhere |
| Alerts | Telegram Bot API | Push notifications for signals + portfolio |
| Secrets | python-dotenv (.env) | API keys + tokens out of codebase |

### Future Additions (Phased)
| Component | Technology | Purpose |
|---|---|---|
| Broker API | IBKR TWS API (ib_insync) | Automated trade execution |
| Deep learning | PyTorch (optional) | Advanced pattern recognition |
| NLP / sentiment | transformers (FinBERT) | Financial news sentiment |
| Data pipeline | pandas + SQLite → PostgreSQL | Scale to larger dataset |
| Geopolitical signals | GDELT dataset (free) | Global events + market correlation |
| Containerisation | Docker | Reproducible environment |
| Cloud (optional) | AWS (EC2 + S3) | Deployment if SaaS |
| MLflow backend | SQLite (mlflow.db) | Replace deprecated filesystem store |

---

## ARCHITECTURE — 5 LAYERS

The five layers form a closed loop. Data flows down through ingestion → AI → ML → execution. Then real outcomes flow **back up** through the feedback engine, improving every layer above it. The system is never static.

┌─────────────────────────────────────────────────────────────┐
│ LAYER 1: DATA INGESTION │
│ SEC EDGAR → S-1/F-1 IPO filings │
│ yfinance → price history + real-time quotes │
│ News RSS → financial headlines │
│ GDELT → geopolitical event data (free, global) │
│ fintel_events.db → 65 market events, 19 regimes, 8 cycles │
└───────────────────────┬─────────────────────────────────────┘
↓
┌─────────────────────────────────────────────────────────────┐
│ LAYER 2: AI CLASSIFICATION + ENRICHMENT │
│ Ollama / Mistral:7b → sector classification │
│ FinBERT → financial news sentiment scoring │
│ LLM agents → qualitative reasoning + summary │
└───────────────────────┬─────────────────────────────────────┘
↓
┌─────────────────────────────────────────────────────────────┐
│ LAYER 3: ML PREDICTION ENGINE ← LIVE AS OF MAR 6, 2026 │
│ 30yr historical IPO data — 4,436 companies, 12 regimes │
│ XGBoost per-regime: Task A (return), B (outcome), C (SPY) │
│ FinTel Score 0–100: 55% Task C + 35% Task B + 10% Task A │
│ Best model: qe3_secular_bull — AUC 0.895, WinRate 69.2% │
│ Backtesting → Sharpe ratio vs S&P500 benchmark │
└───────────────────────┬─────────────────────────────────────┘
↓
┌─────────────────────────────────────────────────────────────┐
│ LAYER 4: DECISION + EXECUTION AGENT │
│ Signal generation → buy / hold / avoid recommendation │
│ Risk guardrails → position sizing, max exposure, tax clock │
│ IBKR TWS API → paper trade (3 months) → live trade │
│ Human confirmation required for every live order │
│ All actions logged to DB — fully auditable, reversible │
└───────────────────────┬─────────────────────────────────────┘
↓
┌─────────────────────────────────────────────────────────────┐
│ LAYER 5: FEEDBACK ENGINE (core design principle) │
│ │
│ Every prediction stored: score, confidence, timestamp │
│ Outcomes measured at: 30 / 90 / 180 / 365 days │
│ Prediction vs actual → error delta calculated │
│ Error > threshold → automatic model retrain triggered │
│ New model evaluated on holdout test set │
│ Better model → promoted to production (MLflow versioned) │
│ Old model archived → instant rollback available │
│ A/B testing: two models run in parallel, winner promoted │
│ │
│ Result: system gets measurably better every month │
│ Efficiency ↑ | Profitability ↑ | Scalability ↑ │
└──────────────────────┬──────────────────────────────────────┘
│
┌────────────┘
│ Feedback flows back up to improve:
│ → Layer 3 (retrain ML models)
│ → Layer 2 (improve AI prompts + classification)
│ → Layer 1 (prioritise better data sources)
↓
[closed loop — system self-improves continuously]

text

---

## CURRENT SYSTEM STATE (as of March 6, 2026)

### What Is Live Right Now
- Dashboard v3.0 at `http://localhost:8501` (laptop) and `http://100.124.81.29:8501` (anywhere via Tailscale + iPhone)
- 6 dashboard pages: Overview, IPO Scanner, Pipeline, Portfolio, Heatmap, System
- IPO Scout scans SEC EDGAR daily at 06:00 CET
- Signal Analyst runs daily at 22:00 CET
- **FinTel AI scores (0–100) visible for all recent filings** — Phase 5 complete
- 3 production-ready ML models (gfc_recovery_qe1_qe2, qe3_secular_bull, pre_gfc_peak)
- qe3_secular_bull is the live fallback for current regime (ai_era_acceleration)
- Portfolio page: live P&L, 183-day tax clock, €3,000 capital progress bar
- Heatmap page: sector intelligence bar chart, scorecard, score distribution box plot
- Telegram bot built and configured — alerts pending final scheduler wiring
- `start_fintel.bat` for one-click dashboard startup with auto browser open

### Key Numbers
| Metric | Value |
|---|---|
| Historical IPOs collected | 4,436 companies |
| Price checkpoints | 41,087 |
| Macro event flags | 49,307 |
| Years covered | 2001–2026 (1996–2000 sparse) |
| Ticker match rate | ~42% (1,873 tickers) |
| Regimes trained | 12 |
| Production-ready regimes | 3 |
| Best model AUC | 0.895 (qe3_secular_bull) |
| Best model WinRate | 69.2% (qe3_secular_bull) |

### Training Results — All Regimes
| Regime | N | AUC | WinRate | Status |
|---|---|---|---|---|
| ai_era_acceleration | 347 | — | — | ⚠️ No test data yet — current regime, resolves mid-2025 |
| gfc_recovery_qe1_qe2 | 214 | 0.827 | 88.9% | ✅ Production ready |
| qe3_secular_bull | 206 | 0.895 | 69.2% | ✅ Production ready — live fallback |
| pre_gfc_peak | 78 | 0.925 | 100% | ✅ Ready (small sample, use carefully) |
| covid_zirp_spac_boom | 156 | 0.836 | — | 🟡 Good AUC, no WinRate test data |
| late_cycle_goldilocks | 113 | 0.917 | 62.5% | 🟡 Just below 63% threshold |
| china_volatility | 113 | 1.000 | 100% | ⚠️ Overfit — small test set |
| rate_hike_shock | 91 | 1.000 | 14.3% | ⚠️ Overfit — inverted signal |
| credit_boom_recovery | 157 | 0.442 | 61.1% | ❌ AUC below 0.5 |
| sarbanes_oxley_era | 75 | 0.596 | 25.0% | ❌ Below threshold |
| svb_stabilisation | 89 | nan | — | ❌ Single-class test set |
| trump_deregulation_bull | 130 | nan | — | ❌ Single-class test set |

### Score Weights (current)
```python
SCORE_WEIGHTS = {
    "task_c_beat_spy_prob": 0.55,   # Task A regression R² weak — shifted weight here
    "task_b_winner_prob":   0.35,
    "task_a_return_norm":   0.10,
}
BEST_FALLBACK = "qe3_secular_bull"
BUILD ROADMAP — PHASED
✅ PHASE 1 — Foundation (COMPLETE — Feb 2026)
 Python 3.14 + venv

 SQLite database with schema

 Config/settings system

 Logging infrastructure (loguru)

 Requirements and project structure

✅ PHASE 2 — IPO Scout Agent (COMPLETE — Feb 2026)
 Fetch S-1/F-1 filings from SEC EDGAR full-text search API

 Fetch company metadata (SIC industry, state of incorporation)

 Classify company sector using Ollama/Mistral

 Score 0–100 based on sector interest

 Save results to SQLite

 Rich colour-coded CLI output table

 Implement incremental scan architecture (historical vs delta)

✅ PHASE 3 — Signal Analyst (COMPLETE — Feb 2026)
 Pull post-IPO price history for tracked companies (yfinance)

 Calculate technical indicators: RSI, MACD, SMA20, SMA50

 Fetch and score news sentiment (Google News RSS + mistral:7b)

 Combine fundamental + technical + sentiment → composite signal

 Update scores daily via APScheduler

 Save signals to database with timestamps

✅ PHASE 4 — Streamlit Dashboard v3.0 (COMPLETE — Mar 6, 2026)
 Overview page: KPI cards, score trend, sector pie, upcoming listings

 IPO Scanner: all filings with sector/type/sort filters + score badges

 Pipeline: 4-tab view (New → Watchlist → Open → Closed)

 Portfolio: live P&L, tax clock, €3,000 capital progress bar

 Heatmap: sector bar chart, scorecard table, box plot distribution

 System: scheduler status, manual controls, DB stats, win rate calculator

 Company detail page: candlestick chart, AI summary, signals, filing info

 Dark theme CSS throughout

 Sidebar navigation with filters (time window + min score)

 CronTrigger scheduler (CET timezone) replacing IntervalTrigger

 Tailscale remote access — accessible from iPhone anywhere in the world

 start_fintel.bat one-click startup

✅ PHASE 5 — ML Training + Live Scoring (COMPLETE — Mar 6, 2026)
Data Infrastructure
 fintel_events.db — 65 market events, 19 regimes, 8 tech cycles, extensible attributes table

 fintel_historical.db — 4,436 IPOs, 41K checkpoints, 49K event flags (2001–2026)

 utils/events_db.py — regime + tech cycle lookups, event windowing

 collect_historical_ipos.py — 30yr SEC EDGAR collection with price checkpoints

ML Training
 scripts/train_models.py — per-regime XGBoost, 3 tasks per regime

 Task A: return regression (MAE metric)

 Task B: 4-class outcome classification (loser/flat/moderate/strong_winner)

 Task C: binary beat-SPY classification (primary signal)

 Temporal train/test split (no data leakage)

 SHAP explanations per regime

 Calibration curves saved per regime

 MLflow experiment tracking

 Per-regime model manifests with metrics

Inference + Scoring
 utils/model_scorer.py — composite FinTel Score formula with regime-aware inference

 scripts/score_new_ipos.py — daily scoring pipeline with CLI flags

 Live FinTel scores visible in dashboard Scanner page

🟡 PHASE 5b — Telegram Alerts (90% COMPLETE — Mar 6, 2026)
 utils/telegram_bot.py — full alert library (high conviction, digest, loss, tax, collection, training)

 BotFather bot created and configured

 Token + chat_id in .env

 Wire 4 Telegram jobs into start_scheduler() in app.py ← one session remaining

🔜 PHASE 6 — Backtest Framework (NEXT)
Goal: Replay historical model predictions against real outcomes. Validate that the FinTel Score has genuine predictive power before deploying real capital.

Outputs needed:

Simulated win rate: if we had traded every score ≥ 75, what would have happened?

Sharpe ratio vs buy-and-hold S&P500

Win rate by regime, sector, score band

Calibration check: does score 80 → 80% actual win rate?

Confusion matrix per regime

Files to build:

scripts/backtest.py

🔜 PHASE 7 — IBKR Paper Trading Agent
⚠️ SAFETY FIRST — this touches real money. Build in order:

Guardrails (non-negotiable before live trading)
python
MAX_POSITION_SIZE    = 500       # €500 max per single position
MAX_PORTFOLIO_EXPOSURE = 3000    # €3,000 max total deployed
MIN_SIGNAL_SCORE     = 75        # Only trade if FinTel score ≥ 75
MIN_CONFIDENCE       = 0.80      # Only trade if model confidence ≥ 80%
REQUIRE_HUMAN_CONFIRM = True     # Always ask before executing live order
TAX_HOLD_DAYS        = 183       # Luxembourg: never auto-sell before 183 days
Steps
Paper trading mode — IBKR TWS API via ib_insync, simulation only, 3 months minimum

Guardrails system — all checks above enforced in code

Trade execution agent — signal → risk check → human confirm → limit order → log

Position monitoring — daily P&L, stop-loss alerts, 183-day tax alerts (never auto-sell)

IBKR Setup Requirements
Open Interactive Brokers account (ibkr.com)

Enable paper trading account (free, separate from live)

Install TWS desktop app — must be running for API

Enable API access: TWS → Edit → Global Configuration → API

pip install ib_insync

🔜 PHASE 8 — Real-Time Public Stock Tracking + Geopolitical Correlation
Goal: Extend FinTel beyond IPOs to S&P500 + NASDAQ100 with breaking news and GDELT geopolitical signals.

Components:

Stock universe: yfinance streaming

News pipeline: Reuters RSS, GDELT (free, 15-min updates), Fed/ECB scraping

FinBERT sentiment scoring on all financial news

Correlation engine: event → price lag analysis, sector rotation detection

LSTM/Transformer for time-series regime detection

Cross-signal: IPO in sector X — is sector X in an uptrend?

🔜 PHASE 9 — Feedback Engine + Continuous Learning
This is what separates FinTel from a static screener. A one-time trained model decays. The feedback engine ensures continuous improvement.

Architecture:

text
Prediction made → stored with score, confidence, model_version, timestamp
        ↓
Real outcome pulled automatically (yfinance) at 30 / 90 / 180 / 365 days
        ↓
Prediction vs actual → error delta
        ↓
Rolling accuracy drops below threshold → trigger retrain
        ↓
New model evaluated on holdout set
        ↓
Better model → promoted (MLflow versioned) | Old model archived
        ↓
A/B test: two models in parallel → winner promoted after 90 days
Three improvement dimensions:

Dimension	Metric
Efficiency	% predicted winners that actually win
Profitability	Sharpe ratio of signals acted on vs benchmark
Scalability	Companies scored per day at same accuracy
INVESTMENT STRATEGY (Luxembourg-Optimised)
Core Rules
Only invest in companies with FinTel score ≥ 75

Minimum model confidence: 80%

Maximum single position: €500 (10% of €5K capital)

Maximum total deployed: €3,000 (60% of capital — 40% always in cash)

ALWAYS hold 183+ days — Luxembourg zero capital gains tax on long-term holdings

Never use leverage

Never invest in companies with < 6 months of post-IPO price history

Tax Calendar
Every position gets a 183-day tax clock in the database

Dashboard shows days remaining for each position

Telegram alert fires at 14 days, 7 days, and day-of tax-free window

Never auto-sell — human decision only

FILE MAP (current)
text
fintel/
├── dashboard/
│   └── app.py                       ← Dashboard v3.0
├── scripts/
│   ├── collect_historical_ipos.py   ← One-time + update historical data
│   ├── train_models.py              ← Per-regime XGBoost training
│   ├── score_new_ipos.py            ← Daily scoring pipeline
│   └── backtest.py                  ← 🔜 Next to build
├── utils/
│   ├── db.py                        ← fintel.db interface
│   ├── events_db.py                 ← fintel_events.db interface
│   ├── model_scorer.py              ← Inference engine + composite score
│   ├── telegram_bot.py              ← Alert bot
│   └── llm.py                       ← GPT summary generation
├── agents/
│   ├── ipo_scout.py                 ← SEC EDGAR scanner
│   └── signal_analyst.py           ← Signal generation
├── models/
│   ├── {regime}/                    ← One folder per trained regime
│   │   ├── task_a.joblib
│   │   ├── task_b.joblib
│   │   ├── task_c.joblib
│   │   ├── encoders.joblib
│   │   └── manifest.json
│   └── plots/                       ← SHAP + calibration charts
├── fintel.db                        ← Live dashboard database
├── fintel_historical.db             ← 30yr IPO training data
├── fintel_events.db                 ← Market events reference DB
├── mlflow_runs/                     ← MLflow experiment logs
├── .env                             ← Secrets (gitignored)
├── start_fintel.bat                 ← One-click dashboard startup
├── PRODUCT_REQUIREMENTS.md         ← This file
├── PROJECT_LOG.md                   ← Session-by-session build log
└── DASHBOARD_GUIDE.md              ← Living user guide for the dashboard
KNOWN ISSUES & TECHNICAL DEBT
Issue	Severity	Planned Fix
ai_era_acceleration untestable (no 1yr price data yet)	Medium	Resolves naturally mid-2025 as 2024 filings age — retrain then
Task A regression R² negative for most regimes	Low	Weight reduced to 10% — acceptable, Task C carries the score
MLflow filesystem backend deprecated Feb 2026	Low	Migrate to sqlite:///mlflow.db before IBKR phase
Telegram scheduler not yet wired into app.py	Low	4 jobs written — one session to wire in
5 unusable regimes (AUC < 0.5 or NaN)	Low	More data over time will fix some; others are genuinely rare
PowerShell ls/Get-ChildItem throws on missing path	Note	Use Test-Path for existence checks — ls is not a safe existence check
DECISIONS LOG
Date	Decision	Reason
2026-02	Use ta instead of pandas-ta	pandas-ta not compatible with Python 3.14
2026-02	SEC EDGAR full-text search API instead of RSS	RSS returns empty results
2026-03-04	Add IBKR trading agent	Extend from research tool to execution platform
2026-03-04	Add backtesting engine with 30yr historical data	Need statistical validation before real money
2026-03-04	Add geopolitical correlation (GDELT)	IPO context is incomplete without macro/news environment
2026-03-04	Elevated feedback engine to core design principle	Self-improvement separates FinTel from a static screener
2026-03-04	Feedback engine targets 3 dimensions: efficiency, profitability, scalability	Accuracy alone is insufficient
2026-03-06	Dual DB architecture: fintel_events.db + fintel_historical.db	Clean separation of reference data vs training data
2026-03-06	Per-regime XGBoost over single global model	Different market eras have fundamentally different IPO dynamics
2026-03-06	Score weights: Task C 55%, Task B 35%, Task A 10%	Task A regression R² negative for most regimes — weak signal
2026-03-06	Best fallback = qe3_secular_bull	Highest AUC (0.895) + WinRate (69.2%) + largest sample (206)
2026-03-06	Tailscale over ngrok/Cloudflare for remote access	Private, permanent, free, native iOS app — most secure option
2026-03-06	Telegram for alerts over email/push	Instant mobile delivery, bot API is free and simple
WHAT THIS TEACHES YOU (Skill Map)
Phase	Skills Earned
1–2 ✅	Python, REST APIs, SQLite, LLM orchestration, CLI tools
3 ✅	yfinance, pandas, technical analysis, news scraping
4 ✅	Streamlit, Plotly, data product design, remote access, mobile UX
5 ✅	ML pipelines, XGBoost, regime segmentation, backtesting, MLflow, inference engines
6 🔜	Historical validation, Sharpe ratio, calibration, statistical significance
7 🔜	Broker APIs, algo trading, risk management, async Python
8 🔜	Real-time data, NLP/FinBERT, correlation analysis, LSTM/Transformers
9 🔜	MLOps, continuous learning, A/B testing, statistical process control
After all phases: ML engineering, MLOps, NLP, quantitative finance systems, real-money algorithmic trading. These are €120–200K/year skills.

This is a living document. Update after every session.
***