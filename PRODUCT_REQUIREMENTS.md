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
| Database | SQLite (built into Python) | Local data store |
| Dashboard | Streamlit + Plotly | Visualisation |
| Technical indicators | ta library | RSI, MACD, SMA, Bollinger Bands |
| Scheduling | APScheduler | Automated daily runs |
| Experiment tracking | MLflow | Model performance logging |

### Future Additions (Phased)
| Component | Technology | Purpose |
|---|---|---|
| Broker API | IBKR TWS API (ib_insync) | Automated trade execution |
| ML models | scikit-learn, XGBoost, LightGBM | Prediction engine |
| Deep learning | PyTorch (optional, Phase 4) | Advanced pattern recognition |
| NLP / sentiment | transformers (FinBERT) | Financial news sentiment |
| Data pipeline | pandas + SQLite → PostgreSQL | Scale to larger dataset |
| Backtesting | Custom engine + bt / backtrader | Historical performance validation |
| Geopolitical signals | GDELT dataset (free) | Global events + market correlation |
| Containerisation | Docker | Reproducible environment |
| Cloud (optional) | AWS (EC2 + S3) | Deployment if SaaS |

---

## ARCHITECTURE — 5 LAYERS

The five layers form a closed loop. Data flows down through ingestion → AI → ML → execution. Then real outcomes flow **back up** through the feedback engine, improving every layer above it. The system is never static.

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 1: DATA INGESTION                                     │
│  SEC EDGAR  → S-1/F-1 IPO filings                          │
│  yfinance   → price history + real-time quotes              │
│  News RSS   → financial headlines                           │
│  GDELT      → geopolitical event data (free, global)        │
└───────────────────────┬─────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│  LAYER 2: AI CLASSIFICATION + ENRICHMENT                     │
│  Ollama / Mistral:7b → sector classification                 │
│  FinBERT             → financial news sentiment scoring      │
│  LLM agents          → qualitative reasoning + summary      │
└───────────────────────┬─────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│  LAYER 3: ML PREDICTION ENGINE                              │
│  10+ years historical IPO data as training set              │
│  Feature engineering: sector, macro, sentiment, timing      │
│  XGBoost / LightGBM → probability score + confidence band   │
│  Backtesting → Sharpe ratio vs S&P500 benchmark             │
│  Error margin calibration before any live capital deployed  │
└───────────────────────┬─────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│  LAYER 4: DECISION + EXECUTION AGENT                         │
│  Signal generation → buy / hold / avoid recommendation      │
│  Risk guardrails → position sizing, max exposure, tax clock │
│  IBKR TWS API → paper trade (3 months) → live trade        │
│  Human confirmation required for every live order           │
│  All actions logged to DB — fully auditable, reversible     │
└───────────────────────┬─────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│  LAYER 5: FEEDBACK ENGINE (core design principle)           │
│                                                             │
│  Every prediction stored: score, confidence, timestamp      │
│  Outcomes measured at: 30 / 90 / 180 / 365 days            │
│  Prediction vs actual → error delta calculated              │
│  Error > threshold → automatic model retrain triggered      │
│  New model evaluated on holdout test set                    │
│  Better model → promoted to production (MLflow versioned)   │
│  Old model archived → instant rollback available            │
│  A/B testing: two models run in parallel, winner promoted   │
│                                                             │
│  Result: system gets measurably better every month         │
│  Efficiency ↑  |  Profitability ↑  |  Scalability ↑        │
└──────────────────────┬──────────────────────────────────────┘
                       │
          ┌────────────┘
          │  Feedback flows back up to improve:
          │  → Layer 3 (retrain ML models)
          │  → Layer 2 (improve AI prompts + classification)
          │  → Layer 1 (prioritise better data sources)
          ↓
     [closed loop — system self-improves continuously]
```

---

## BUILD ROADMAP — PHASED

### ✅ PHASE 1 — Foundation (COMPLETE)
**Skills learned:** Python project setup, SQLite, virtual environments, config management

- [x] Python 3.14 + venv
- [x] SQLite database with schema
- [x] Config/settings system
- [x] Logging infrastructure (loguru)
- [x] Requirements and project structure

---

### ✅ PHASE 2 — IPO Scout Agent (COMPLETE)
**Skills learned:** REST APIs, SEC EDGAR, JSON parsing, local LLM orchestration, rich CLI, incremental data pipelines

- [x] Fetch S-1/F-1 filings from SEC EDGAR full-text search API
- [x] Fetch company metadata (SIC industry, state of incorporation)
- [x] Classify company sector using Ollama/Mistral
- [x] Score 0–100 based on sector interest
- [x] Save results to SQLite
- [x] Rich colour-coded CLI output table
- [x] Run first real scan and validate outputs
- [x] Implement incremental scan architecture (historical vs delta)

---

### ✅ PHASE 3 — Signal Analyst (COMPLETE)
**Skills learned:** yfinance, technical indicators, pandas data manipulation, news scraping

- [x] Pull post-IPO price history for tracked companies (yfinance)
- [x] Calculate technical indicators: RSI, MACD, SMA20, SMA50
- [x] Fetch and score news sentiment (Google News RSS + mistral:7b)
- [x] Combine fundamental + technical + sentiment → composite signal
- [x] Update scores daily via APScheduler (`agents/scheduler.py`)
- [x] Save signals to database with timestamps

---

### 🔜 PHASE 4 — Streamlit Dashboard (IN PROGRESS) ← **YOU ARE HERE**
**Skills learned:** Streamlit, Plotly, data visualisation, UX for data products

- [x] IPO pipeline view (new → tracked → positioned → closed)
- [x] Individual company deep-dive page (chart + indicators + AI summary)
- [x] Portfolio tracker with Luxembourg 183-day tax countdown per position (badge & countdown added)
- [x] Realised P/L display for closed positions
- [x] Alerts for large losses or nearing tax-free date
- [x] Signal history and model accuracy metrics (button on System page)
- [ ] Signal history and model accuracy metrics
- [ ] Background worker to precompute scans, signals and metrics outside the UI
- [ ] System/status page showing job timestamps and manual agent controls
- [ ] Sector heatmap (which sectors are producing most signals)
- [ ] Upcoming listings filter/card using `get_upcoming_listings()` helper and calendar cache
- [ ] Dashboard link to run calendar backfill script (`scripts/backfill_calendar.py`) or schedule via scheduler

---

### 🔜 PHASE 5 — Backtesting Engine + Temporal Segmentation (NEW)
**Skills learned:** Historical data pipelines, regime detection, temporal weighting, ML evaluation, statistical validation

**Goal:** Train ML models across the full history of US IPOs — but not naïvely. Different market eras behave differently. A model trained on dot-com era data may be actively harmful for predicting today's AI IPOs. We train in segments first, compare across segments, then combine intelligently with relevance weighting.

---

#### Step 1 — Data Collection (Full History)
- Pull ALL S-1/F-1 filings from SEC EDGAR from 1996 (EDGAR electronic filing start) to present
- For each company: identify their ticker post-listing, then pull full price history from yfinance
- Outcome labels at: 1 year / 3 years / 5 years / 10 years post-IPO
- Label each outcome as: **Strong Winner** (>50%) / **Moderate** (0–50%) / **Flat** (±10%) / **Loser** (<0%) / **Delisted**
- Result: ~30 years of IPO data, thousands of companies, labelled outcomes

---

#### Step 2 — Market Regime Segmentation
Before training anything, split the full history into named **market regime segments**. Each segment has distinct macro conditions that affect IPO behaviour differently:

| Segment | Period | Regime Characteristics |
|---|---|---|
| **Dot-com Boom** | 1996–2000 | Extreme tech euphoria, P/E ratios irrelevant, retail FOMO |
| **Post-Crash Recovery** | 2001–2006 | Cautious market, back-to-fundamentals, lower IPO volume |
| **Pre-GFC Bubble** | 2006–2008 | Leverage-driven growth, financial sector dominance |
| **GFC + Recovery** | 2008–2012 | Crash + rebuilding, government intervention, flight to safety |
| **QE Era** | 2012–2018 | Near-zero rates, easy money, tech unicorn IPOs surge |
| **COVID Shock + SPAC Boom** | 2019–2021 | Pandemic volatility, stimulus excess, SPAC explosion |
| **Rate Hike & Reset** | 2022–2023 | Hikes, valuation compression, high IPO failure rate |
| **AI Era** | 2024–present | AI sector dominance, renewed tech appetite |

---

#### Step 3 — Segment-by-Segment Model Training (Round 1)
Train a separate ML model on each regime segment independently:

```
For each segment S:
  → Train XGBoost / LightGBM on IPOs filed within S
  → Evaluate: accuracy, precision, recall, AUC-ROC, calibration curve
  → Log to MLflow with segment label and date range
  → Record: what features mattered most in this regime? (SHAP values)
  → Record: which sectors outperformed in this regime?
```

**Output of Step 3:** One model per regime. Eight models. A clear picture of:
- Which scoring features are universally predictive (appear in all regimes)
- Which are regime-specific (e.g. P/E ratio matters post-2001, irrelevant 1996–2000)
- How IPO success rates vary by era

---

#### Step 4 — Full Lookback Model Training (Round 2)
Now train a single model on **all data combined** (max lookback, 1996–present):

```
→ Train XGBoost / LightGBM on full dataset
→ Compare accuracy vs each segment model
→ Key question: does more data always help, or does older data add noise?
→ Log to MLflow alongside segment models for direct comparison
```

**This answers:** Is a 30-year model better or worse than a 5-year model?

---

#### Step 5 — Temporal Relevance Analysis
Compare segment models vs full lookback model to understand **which time periods have predictive relevancy for today's market**:

```
Define relevancy score per segment:
  - How similar is the macro environment of segment S to today?
  - How accurately did a model trained on S predict the next segment's outcomes?
  - What is the performance decay as we go further back in time?
```

Expected findings (hypotheses to test):
- **Recent segments (2022–present)** = highest relevance for current predictions
- **QE Era (2012–2018)** = partially relevant (similar tech-led IPO market)
- **Dot-com Era (1996–2000)** = lowest relevance (market structure too different)
- **GFC period** = relevant only for macro shock scenarios

---

#### Step 6 — Weighted Ensemble Model (Final Production Model)
Combine insights from all segments into a single production model using **time-decay weighting**:

```python
# Conceptual weighting logic
SEGMENT_WEIGHTS = {
    "ai_era_2024_present":     1.00,   # maximum relevance
    "rate_hike_reset_2022":    0.85,
    "covid_spac_2019_2021":    0.70,
    "qe_era_2012_2018":        0.55,
    "gfc_recovery_2008_2012":  0.30,
    "pre_gfc_2006_2008":       0.20,
    "post_crash_2001_2006":    0.15,
    "dotcom_boom_1996_2000":   0.05,   # near-zero relevance for today
}
# Note: weights are initial hypotheses — Step 5 analysis will set the real values
```

- Train final model with sample weights matching temporal relevance scores
- Heavier weighting on recent regime data; older data still included but down-weighted
- This gives the model long-term structural pattern awareness + recent market sensitivity
- Re-evaluate weights every 6 months as new regimes emerge

---

#### Step 7 — Error Margin Calibration
- For each model version: when it says 80% probability, does 80% actually happen?
- Use Platt scaling or isotonic regression to calibrate probability outputs
- Define minimum calibration quality required before any live capital deployment
- Log calibration curves in MLflow for all model versions

---

#### Feature Engineering (Universal)
Built for every IPO across all time periods:
```
Company fundamentals (at time of filing):
  - Sector + SIC industry code
  - State of incorporation
  - Market cap at IPO price
  - Revenue, net income/loss, burn rate (from S-1 financials)
  - Years since founding at IPO date
  - Underwriter tier (Goldman, Morgan Stanley = tier 1 vs unknown = tier 3)

Macro context (at time of filing):
  - S&P500 level + trailing 6-month return
  - Federal Funds Rate
  - VIX (market fear index)
  - Market regime label (from Step 2 above)
  - IPO market temperature (# of IPOs filed in last 90 days)

Sentiment + timing:
  - News sentiment score at IPO date
  - Sector trend at time of filing (is this sector hot?)
  - Time of year (Q4 IPOs behave differently to Q1)

Post-IPO technicals (for training labels):
  - Price at 30 / 90 / 180 / 365 days vs IPO price
  - Volume trend in first 30 days
  - Whether company survived to 3 years
```

---

#### Output
- Eight segment models + one full lookback model + one weighted ensemble model
- Temporal relevance map: which eras matter most for today's predictions
- Backtested Sharpe ratio of ensemble vs buy-and-hold S&P500
- Win rate at different probability thresholds (defines the score cutoff for live trading)
- All experiments tracked in MLflow with full reproducibility

---

### 🔜 PHASE 6 — IBKR Trading Agent (NEW)
**Skills learned:** Broker API, algorithmic trading, risk management, async Python

**⚠️ SAFETY FIRST — this touches real money. Build in order:**

#### Step 1: Paper Trading Mode
- Connect to IBKR TWS API using `ib_insync` library
- Paper trade account only — no real money
- Agent sends orders but they execute in simulation
- Run for minimum 3 months before live money

#### Step 2: Guardrails System (non-negotiable before live trading)
```python
MAX_POSITION_SIZE = 500          # €500 max per single position
MAX_PORTFOLIO_EXPOSURE = 3000    # €3,000 max total deployed
MIN_SIGNAL_SCORE = 75            # Only trade if ML score ≥ 75
MIN_CONFIDENCE = 0.80            # Only trade if model confidence ≥ 80%
REQUIRE_HUMAN_CONFIRM = True     # Always ask before executing live order
TAX_HOLD_DAYS = 183              # Luxembourg: never auto-sell before 183 days
```

#### Step 3: Trade Execution Agent
```
Signal score ≥ threshold
    ↓
Risk guardrails check (position size, exposure, tax days)
    ↓
Generate order proposal → print to terminal for review
    ↓
Human confirmation required (type YES to proceed)
    ↓
IBKR API → place limit order
    ↓
Log everything to database (order ID, price, timestamp)
    ↓
Set 183-day tax calendar alert
```

#### Step 4: Position Monitoring
- Daily check on all open positions
- Alert if stop-loss level breached
- Alert when 183-day hold period completes (tax-free window opens)
- Never auto-sell — only auto-alert

#### IBKR Setup Requirements
- Open Interactive Brokers account (ibkr.com)
- Enable paper trading account (free, separate from live)
- Install TWS (Trader Workstation) desktop app — must be running for API
- Enable API access in TWS settings (Edit → Global Configuration → API)
- Library: `pip install ib_insync`

---

### 🔜 PHASE 7 — Real-Time Public Stock Tracking + Geopolitical Correlation (NEW)
**Skills learned:** Real-time data streams, NLP at scale, correlation analysis, macro modelling

**Goal:** Extend FinTel beyond IPOs to track all publicly traded stocks and correlate with:
- Breaking financial news (earnings, guidance, M&A)
- Central bank policy (Fed, ECB rate decisions)
- Geopolitical events (wars, sanctions, elections, trade policy)
- Sector trends and rotation signals

#### Components
1. **Stock Universe**: S&P 500 + NASDAQ 100 + watchlist (yfinance streaming / websocket)
2. **News Pipeline**: 
   - Financial news: Reuters, Bloomberg RSS, Seeking Alpha
   - Geopolitical: GDELT dataset (free, updated every 15 minutes globally)
   - Central bank: Fed / ECB statement scraping
3. **Sentiment Engine**: FinBERT (pre-trained financial NLP model) for sentiment scoring
4. **Correlation Engine**:
   - Event → price move correlation matrix
   - Lag analysis (does this news type move price in 1 hour? 1 day? 1 week?)
   - Sector rotation detection (money moving from tech → defence etc.)
5. **Trend Prediction**:
   - LSTM or Transformer model for time-series pattern recognition
   - Regime detection (bull/bear/sideways)
   - Probability-weighted price target ranges
6. **Portfolio Integration**:
   - Cross-signal between IPO pipeline and real-time market data
   - "IPO in sector X — is sector X currently in an uptrend?" 

---

### 🔜 PHASE 8 — Feedback Engine + Continuous Learning (NEW)
**Skills learned:** MLOps, model retraining pipelines, A/B testing, statistical process control

> ⚠️ **This is not a "nice to have" — it is what separates FinTel from a static screener.**  
> A one-time trained model decays in accuracy as markets evolve. The feedback engine ensures FinTel continuously improves its efficiency (correct predictions), profitability (return on signals acted on), and scalability (can handle more companies/signals without degrading).

**Goal:** Every prediction is an experiment. Every outcome is a data point. The system learns from reality and gets better month over month.

#### Feedback Architecture
```
Prediction made → stored in DB with:
  - company_id, score, confidence, sector, timestamp, model_version
    ↓
Actual outcome measured automatically (yfinance price pull):
  - at 30 days: early momentum signal
  - at 90 days: medium-term validation
  - at 180 days: tax-hold window check
  - at 365 days: primary performance benchmark
    ↓
Prediction vs actual → error delta calculated per prediction
    ↓
Aggregate error across last N predictions:
  - If rolling accuracy drops below threshold → trigger retrain
  - If calibration drift detected → trigger recalibration
    ↓
Retrain model on expanded dataset (old data + new outcomes)
    ↓
New model evaluated on holdout test set (data it never saw)
    ↓
If new model beats current production model → promote
    ↓
Old model version archived in MLflow → instant rollback available
    ↓
Dashboard updated: show accuracy trend, model version history
```

#### Three Dimensions of Improvement
| Dimension | What Improves | How It's Measured |
|---|---|---|
| **Efficiency** | Prediction accuracy | % of predicted winners that actually win |
| **Profitability** | Risk-adjusted return | Sharpe ratio of signals acted on vs benchmark |
| **Scalability** | Throughput without accuracy loss | # companies scored per day at same accuracy |

#### Metrics Tracked Over Time
- Rolling 90-day prediction accuracy (per sector + overall)
- Calibration curve: when model says 80%, does 80% actually happen?
- Calibration drift: is accuracy degrading? Trigger retrain if yes
- Signal quality by sector — which sectors is the model best/worst at?
- Cost per correct signal vs cost per false positive (expected value)
- Model version history: v1, v2, v3... with performance at each version

#### A/B Testing Framework
- Split incoming IPOs: 50% scored by Model A, 50% by Model B
- Compare real performance outcomes after 90 days
- Promote winner to 100% traffic, retire loser
- Archive both in MLflow — full audit trail

#### Scalability Path
As feedback loop matures and accuracy is statistically proven:
- Increase capital allocation (from €5K → larger)
- Add more tracked sectors
- Expand to real-time public stocks (connects to Phase 7)
- Consider SaaS: sell access to the signal feed (subscribers pay for the model's edge)

---

## INVESTMENT STRATEGY (Luxembourg-Optimised)

### Core Rules
1. Only invest in companies with composite ML score ≥ 75
2. Minimum model confidence: 80%
3. Maximum single position: €500 (10% of €5K capital)
4. Maximum total deployed: €3,000 (60% of capital — 40% always in cash)
5. **ALWAYS hold 183+ days** — Luxembourg zero capital gains tax on long-term holdings
6. Never use leverage
7. Never invest in companies with <6 months of post-IPO price history

### Tax Calendar
- Every position gets a 183-day tax clock in the database
- Dashboard shows days remaining for each position
- Alert fires when tax-free window opens
- Never auto-sell — human decision only

---

## UPDATED REQUIREMENTS.TXT

See `requirements.txt` for current packages.

**Future additions (add when phase requires them):**
```
# Phase 5 — Backtesting + ML
scikit-learn
xgboost
lightgbm
mlflow
shap                    # ML explainability — understand WHY model made a prediction

# Phase 6 — IBKR Trading Agent
ib_insync               # Interactive Brokers API wrapper

# Phase 7 — Real-time + NLP
transformers            # FinBERT sentiment model (HuggingFace)
torch                   # PyTorch (required by transformers)
gdelt-doc               # GDELT geopolitical dataset client

# Phase 8 — Advanced
statsmodels             # Statistical modelling, hypothesis testing
scipy                   # Scientific computing, distributions
optuna                  # Hyperparameter tuning (better than grid search)
```

---

## WHAT THIS TEACHES YOU (Skill Map)

Each phase maps directly to real, provable, resume-worthy skills:

| Phase | Skills Earned |
|---|---|
| 1-2 ✅ | Python, REST APIs, SQLite, LLM orchestration, CLI tools |
| 3 | yfinance, pandas, technical analysis, news scraping |
| 4 | Streamlit, Plotly, data product design |
| 5 | ML training pipelines, backtesting, statistical validation, MLflow |
| 6 | Broker APIs, algo trading, risk management, async Python |
| 7 | Real-time data, NLP/FinBERT, correlation analysis, LSTM/Transformers |
| 8 | MLOps, continuous learning, A/B testing, statistical process control |

**After all 8 phases:** You can legitimately claim experience in ML engineering, MLOps, NLP, quantitative finance systems, and real-money algorithmic trading. These are €120-200K/year skills.

---

## DECISIONS LOG

| Date | Decision | Reason |
|---|---|---|
| 2026-02 | Use `ta` instead of `pandas-ta` | pandas-ta not compatible with Python 3.14 |
| 2026-02 | SEC EDGAR full-text search API instead of RSS | RSS returns empty results |
| 2026-03 | Add IBKR trading agent | Extend from research tool to execution platform |
| 2026-03 | Add backtesting engine with 10yr historical data | Need statistical validation before real money |
| 2026-03 | Add geopolitical correlation (GDELT) | IPO context is incomplete without macro/news environment |
| 2026-03 | Elevated feedback engine to core design principle (not Phase 8 add-on) | Self-improvement is what separates FinTel from a static screener — must be in the architecture from day one of design thinking |
| 2026-03 | Feedback engine targets 3 dimensions: efficiency, profitability, scalability | Each dimension has its own metric — accuracy alone is insufficient |

---

*This is a living document. Update the status checkboxes and Decisions Log as you build.*
