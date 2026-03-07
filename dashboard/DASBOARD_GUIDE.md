
# 🧠 FinTel Dashboard — Complete User Guide
> **Version:** 3.0 | **Last Updated:** March 6, 2026
> This file updates automatically every time a new feature is added.
> Run: `streamlit run dashboard/app.py` → `http://localhost:8501`

---

## How the Dashboard Works — Big Picture

SEC EDGAR → IPO Scout → fintel.db → Signal Analyst → Scores
↓
Dashboard reads fintel.db
↓
Overview / Scanner / Pipeline / Portfolio / Heatmap

text

The dashboard **never writes data** — it only reads from `fintel.db`.
All data collection and scoring happens in background scripts and the scheduler.

---

## 🔧 The Sidebar

┌─────────────────────────┐
│ 🧠 FinTel │
│ AI-powered IPO intel │
│─────────────────────────│
│ 🏠 Overview │ ← Default landing page
│ 🔍 IPO Scanner │ ← Browse all filings
│ 📈 Pipeline │ ← Your working list
│ 💼 Portfolio │ ← Live positions + P&L
│ 🔥 Heatmap │ ← Sector intelligence
│ ⚙️ System │ ← Controls + scheduler
│─────────────────────────│
│ FILTERS │
│ Time window: [60 days▼] │ ← Affects ALL pages
│ Min score: [50 ──●──] │ ← Filters low-quality
│─────────────────────────│
│ Refreshed: 20:46:03 │
│ 🔄 Refresh data │ ← Clears 5-min cache
└─────────────────────────┘

text

### Sidebar Filters — What They Do
| Filter | What it controls | Good defaults |
|---|---|---|
| **Time window** | How far back to look for filings | 60d for active, 180d for research |
| **Min score** | Hide anything below this threshold | 50 for browsing, 70 for action |
| **Refresh data** | Clears the 5-minute cache and reloads from DB | Use after running scout |

---

## 🏠 Overview Page

┌──────────┬──────────┬──────────┬──────────┬──────────┐
│📋 Filings│🎯 High │⭐Watchlist│💼 Open │📅 Upcoming│
│ Scanned │Conviction│ │Positions │ Listings │
│ 142 │ 18 │ 7 │ 3 │ 5 │
│Last 60d │Score ≥75 │ Tracked │ Active │Next 90d │
└──────────┴──────────┴──────────┴──────────┴──────────┘

┌─────────────────────────┐ ┌──────────────┐
│ 📈 Score Trend │ │ 🥧 Sectors │
│ │ │ │
│ ···· · │ │ Pie chart │
│ · ·· · │ │ of top 8 │
│· ····· │ │ sectors by │
│ ----75 threshold---- │ │ filing count│
└─────────────────────────┘ └──────────────┘

📅 Upcoming Listings (next IPOs confirmed for listing)
🎯 Recent High Conviction (top 5 scores right now)

text

### What Each KPI Means
| KPI | Definition | Action signal |
|---|---|---|
| **Filings Scanned** | Raw S-1/F-1 filings pulled from SEC EDGAR in your time window | Low = run the scout |
| **High Conviction** | Filings with FinTel score ≥ 75 | >5 = active market |
| **Watchlist** | Companies you've manually starred | Should mirror your research list |
| **Open Positions** | Actual trades you've entered in Portfolio | Track vs €3,000 max |
| **Upcoming Listings** | Companies with confirmed listing dates in next 90 days | Timing for entry |

### Score Trend Chart
- **X-axis:** Weeks (grouped by filing week)
- **Y-axis:** Average FinTel score (0–100)
- **Green dashed line:** High conviction threshold (75)
- **Interpretation:** A rising trend = improving deal quality in the market.
  A flat/low trend = weak IPO market, be selective.

### Sector Pie
- Shows which sectors are filing the most IPOs right now
- **Important:** This is *filing volume*, not *quality*. A big sector slice
  doesn't mean those companies are good — check the Heatmap for quality.

---

## 🔍 IPO Scanner Page

Filters: [Sector ▼] [Filing Type ▼] [Sort by ▼]
──────────────────────────────────────────────────
142 filings

Company Name Sector Score Type Date [View]
──────────────────────────────────────────────────────────────────
CoreWeave Inc Technology 87 S-1 2026-02 View →
Klarna Group Fintech 81 F-1 2026-01 View →
StubHub Holdings Marketplace 74 S-1 2025-12 View →
...

text

### Scanner Filters
| Filter | Options | Use when |
|---|---|---|
| **Sector** | All / individual sectors | You want to focus on a theme (e.g. AI infrastructure) |
| **Filing Type** | S-1 (US domestic) / F-1 (foreign private issuer) | F-1 = foreign companies listing in US (riskier, different rules) |
| **Sort by** | Score ↓ / Date ↓ / Company ↑ | Score for research, Date for monitoring new arrivals |

### Score Colour Coding
| Colour | Score Range | Meaning |
|---|---|---|
| 🟢 Green | ≥ 75 | High conviction — models agree this is worth watching |
| 🟡 Yellow | 55–74 | Medium — monitor but don't act yet |
| 🔴 Red | < 55 | Low quality or in a bad macro regime |

### Company Detail (click View →)
Opens a full page with 4 tabs:
- **📊 Price Chart** — Candlestick + volume. Only shows if company has listed and has a ticker.
- **🧠 AI Summary** — GPT-generated analysis of the SEC filing. Click "Generate" to trigger.
- **📡 Signals** — All historical signal events for this ticker from the signal analyst.
- **📄 Filing Info** — Raw CIK, SIC code, state of incorporation, SEC link.

---

## 📈 Pipeline Page

Your personal working list — moves a company from "interesting" to "position".

[🆕 New Filings] [⭐ Watchlist] [💼 Open Positions] [✅ Closed Trades]

text

### Tab 1 — New Filings
Same as Scanner but with quick-action buttons:
- **⭐ (star icon):** Adds to watchlist instantly
- **→ (arrow):** Opens company detail

### Tab 2 — Watchlist
Companies you've decided to monitor:
- **➖ Remove:** Takes off watchlist
- **→:** Full detail view

### Tab 3 — Open Positions
Positions you've entered:
- Shows live price vs buy price (fetched from yfinance every 60s)
- **P&L in %** and **euros**
- **Tax clock:** Luxembourg 183-day rule tracker
  - Grey: holding, days remaining shown
  - Orange warning: ≤14 days to tax-free threshold
  - Green: ✅ tax-free (>183 days held)
- 🔴 red label = position down >10% → review stop-loss

### Tab 4 — Closed Trades
All exited positions with realised P&L and win rate.

---

## 💼 Portfolio Page

Dedicated performance view with capital controls.

📊 Performance Summary
┌──────────┬──────────┬──────────┬──────────┐
│ Closed │ Win Rate │ Avg │ Total │
│ Trades │ │ Return │ P&L │
│ 12 │ 67% │ +28.4% │ +€1,240 │
└──────────┴──────────┴──────────┴──────────┘

📈 Open Positions (expandable cards)

Capital deployed: €1,400 / €3,000 ████████░░░░ (€1,600 available)

text

### Capital Progress Bar
- Maximum €3,000 deployed at any time (FinTel risk rule)
- Bar turns red when you exceed €2,700 (90%)
- Remaining capital shown for next trade sizing

### Win Rate (Closed Trades)
- Calculated as: trades with positive P&L / total closed trades
- **Target:** ≥ 63% (aligned with model quality threshold)
- Updates live as you close positions

---

## 🔥 Heatmap Page

The sector intelligence layer — answers "where is the quality?"

KPIs: Sectors Tracked: 14 | Hottest: AI/ML (23 HC signals) | Hot Sectors: 4

┌─────────────────────────────────┐ ┌──────────────────────────┐
│ Signal Density Bar Chart │ │ Sector Scorecard │
│ │ │ │
│ AI/ML ██████████ 23 │ │ Sector Total Avg HC │
│ SaaS ███████ 17 │ │ AI/ML 47 78 23 │
│ Fintech █████ 12 │ │ SaaS 38 71 17 │
│ Biotech ████ 9 │ │ Fintech 29 65 12 │
│ (color = avg score) │ │ (green ≥75, yellow ≥60) │
└─────────────────────────────────┘ └──────────────────────────┘

Score Distribution by Sector (box plot)
┌──────────────────────────────────────────────────────────────┐
│ Each box = spread of scores in that sector │
│ Outlier dots = individual filings │
│ ----75 line = high conviction threshold │
└──────────────────────────────────────────────────────────────┘

🚨 Hot Sectors Right Now
✅ AI/ML — 23 high-conviction signals | avg score 78 | latest: 2026-03-04
✅ SaaS — 17 high-conviction signals | avg score 71 | latest: 2026-02-28

text

### Bar Chart — Signal Density
- **Bar length:** Number of high-conviction (≥75) signals in the sector
- **Bar colour:** Average score (red=low, yellow=medium, green=high)
- **Use this to:** Identify which sectors to focus research on

### Scorecard Table
- **Total:** Raw filing count
- **HC (≥75):** High conviction count — the number that matters
- **MC (≥55):** Medium conviction — worth watching
- **Colour coding:** Green/yellow/red based on avg score quality

### Box Plot — Score Distribution
- Each box shows the **spread** of scores in a sector
- Tall boxes = inconsistent quality (some great, some terrible)
- Narrow boxes = consistent quality sector
- Dots above box = exceptional individual companies worth investigating

---

## ⚙️ System Page

🕐 Scheduled Jobs
IPO Scout Daily 06:00 CET ✅ 2026-03-06 06:00:12
Calendar Refresh Daily 07:00 CET ✅ 2026-03-06 07:00:08
Signal Analyst Daily 22:00 CET Not run yet
Portfolio Metrics Daily 22:30 CET Not run yet
Price Cache Daily 05:30 CET ✅ 2026-03-06 05:30:45
AI Summaries Daily 23:30 CET Not run yet

▶ Manual Controls
[▶ Run IPO Scout] [▶ Refresh Calendar] [📊 30d Win Rate]
[▶ Run Signals] [▶ Portfolio Metrics] [🗑 Clear Cache]

📦 Database Stats
ipo_filings: 847 rows
watchlist: 12 rows
portfolio: 3 rows
signals: 234 rows

text

### Scheduler Jobs
| Job | What it does | Why it matters |
|---|---|---|
| **IPO Scout** | Scans SEC EDGAR for new S-1/F-1 filings | Primary data feed — new companies discovered here |
| **Calendar Refresh** | Queries IPO calendars for confirmed listing dates | Updates "expected listing" in company detail |
| **Signal Analyst** | Runs scoring models on all unscored filings | Keeps FinTel scores fresh |
| **Portfolio Metrics** | Refreshes P&L, live prices for open positions | Portfolio page accuracy |
| **Price Cache** | Downloads latest prices for watchlist tickers | Faster chart loading in detail pages |
| **AI Summaries** | (Future) Auto-generates GPT summaries overnight | Remove manual generate step |

### Manual Controls
Use these when you want to trigger a job immediately without waiting for schedule:
- **Run IPO Scout** → new filings appear in Scanner instantly
- **Clear Cache** → forces fresh data read (use after manual DB changes)
- **30d Win Rate** → checks how accurate signals have been recently

---

## 🧠 FinTel Score — How It's Calculated

Once `train_models.py` is run, every filing gets a **FinTel Score (0–100)**:

FinTel Score = 45% × Beat-SPY Probability
+ 35% × Winner Class Probability
+ 20% × Expected Return (normalised)

Verdict thresholds:
≥ 75 → 🟢 Strong Buy
≥ 60 → 🟡 Watch
≥ 45 → ⚪ Neutral
< 45 → 🔴 Avoid

text

Each score also shows:
- **Beat-SPY Prob:** Probability this company outperforms S&P500 in 1 year
- **Expected Return:** Point estimate from regression model (e.g. +34%)
- **Winner Prob:** Probability of being classified "strong_winner" outcome
- **Regime:** Market regime at filing date (e.g. `ai_era_acceleration`)
- **Confidence:** High/Medium/Low based on training data size for that regime

---

## 📁 File Map

fintel/
├── dashboard/
│ └── app.py ← This dashboard (v3.0)
├── scripts/
│ ├── collect_historical_ipos.py ← One-time historical data pull
│ ├── train_models.py ← Per-regime ML training
│ └── score_new_ipos.py ← Scores live filings daily
├── utils/
│ ├── db.py ← fintel.db interface
│ ├── events_db.py ← fintel_events.db interface
│ ├── model_scorer.py ← Inference engine
│ └── llm.py ← GPT summary generation
├── agents/
│ ├── ipo_scout.py ← SEC EDGAR scanner
│ └── signal_analyst.py ← Signal generation
├── models/
│ ├── {regime}/ ← One folder per trained regime
│ │ ├── task_a.joblib ← Regression model
│ │ ├── task_b.joblib ← Classification model
│ │ ├── task_c.joblib ← Binary model
│ │ ├── encoders.joblib ← Feature encoders
│ │ └── manifest.json ← Metrics + metadata
│ └── plots/ ← SHAP + calibration charts
├── fintel.db ← Live dashboard database
├── fintel_historical.db ← 30yr IPO historical data
└── fintel_events.db ← Market events reference DB

text

---

## 🔄 Changelog

| Date | Version | Change |
|---|---|---|
| Mar 6, 2026 | v3.0 | Tailscale remote access — dashboard live on iPhone from anywhere |
| Mar 6, 2026 | v3.0 | FinTel AI scores (0–100) now visible in Scanner — Phase 5 complete |
| Mar 6, 2026 | v3.0 | Score weights updated: Task C 55%, Task B 35%, Task A 10% |
| Mar 6, 2026 | v3.0 | Best fallback regime: qe3_secular_bull (AUC 0.895, WinRate 69.2%) |

| Mar 6, 2026 | v3.0 | Full dashboard rewrite. Fixed scheduler, navigation, added Heatmap page |
| Mar 6, 2026 | v3.0 | Added `fintel_events.db` reference layer with 65 events, 19 regimes |
| Mar 6, 2026 | v3.0 | Added `model_scorer.py` inference engine and `score_new_ipos.py` |
| Mar 5, 2026 | v2.x | Portfolio page, tax clock, signal history |
| Mar 4, 2026 | v1.x | Initial dashboard with Scanner and Pipeline |