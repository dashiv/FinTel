# FinTel — Project Log
**Format:** Minimal events log. One entry per significant action.  
**Updated by:** AI assistant (Antigravity) after every meaningful change.  
**Rule:** Never delete entries. Append only. Most recent at top.

---

## HOW TO READ THIS LOG

Each entry = one significant event: a design decision, a file created/changed, a feature built, a scan run, an error resolved, or a session summary.

---

## LOG

---

## Session: March 6, 2026

### Completed
- ✅ Architected dual-DB design: `fintel_events.db` (reference) + `fintel_historical.db` (IPO data)
- ✅ Built `utils/events_db.py` — 65 events, 19 market regimes, 8 tech cycles, extensible via `event_attributes`
- ✅ Built `collect_historical_ipos.py` v3 — currently running overnight (1996–2026)
- ✅ Built `train_models.py` — per-regime XGBoost, 3 tasks (regression + 4-class + binary beat-SPY)
- ✅ Rebuilt `app.py` → v3.0 — fixed all syntax/logic errors, added Heatmap page
- ✅ Built `utils/model_scorer.py` — inference engine with composite FinTel Score formula
- ✅ Built `scripts/score_new_ipos.py` — daily scoring pipeline
- ✅ Created `DASHBOARD_GUIDE.md` — living documentation file

### Running Overnight
- 🔄 `collect_historical_ipos.py` — collecting 30yr of IPO data

### Tomorrow Sequence
1. Check collection complete
2. `python scripts/train_models.py`
3. `mlflow ui` to review per-regime metrics
4. `python scripts/score_new_ipos.py --days 90`
5. Refresh dashboard → first AI-scored signals visible

### 2026-03-05 — AI Summary & Test Hardening (Complete)

**Agent:** Antigravity (Claude Haiku 4.5)  
**Session focus:** Fix setter logic, enhance error handling, auto-summary generation, dashboard polish

- **Fixed `set_ai_summary()` semantics:** Now returns `False` when filing doesn't exist (was always `True`), enabling proper error detection by callers.
- **Enhanced dashboard AI summary:** Button now checks return value and displays user-friendly error if filing not found.
- **Scheduler enhancement:** Added automated `daily_ai_summaries()` job to generate and store summaries for tracked companies (scheduled 23:30 CET daily).
- **Test isolation:** Rewrote all tests to use isolated temporary databases (`setup_temp_db()` / `teardown_temp_db()`), eliminating cross-test contamination.
- **Error handling:** Added graceful warning logs in scheduler when summary save fails (prevents silent failures).
- **Portfolio performance section:** Added new Dashboard KPIs for closed trades: win rate, avg return %, total P/L in €.
- **CI/CD readiness:** All tests now pass; GitHub Actions workflow ready to validate on push (`.github/workflows/ci.yml`).

**Tests status:** ✅ All 2 test suites passing  
**Code quality:** ✅ Syntax valid, no import cycles  
**Next action:** Push to GitHub to trigger CI workflow (`git push origin main` once Git installed)

---
### 2026-03-05 — Pipeline View & Portfolio Helpers

**Agent:** Antigravity (Raptor mini)  
**Session focus:** IPO pipeline UI and DB helpers for closed positions

- Added IPO Pipeline page with tabs for new filings, watchlist, open positions, and closed trades.
- Implemented `get_closed_positions()` in `utils/db.py` and made `get_portfolio()` optionally return all records.
- Added buttons to move watchlist entries to portfolio and view details from pipeline.
- Updated sidebar radio to include 📈 Pipeline.

### 2026-03-05 — Portfolio Enhancements

**Agent:** Antigravity (Raptor mini)  
**Session focus:** Realised P/L, tax countdown, loss alerts

- Added realised P/L calculations (pct & euro) for closed trades.
- Displayed P/L on closed tab with colour coding.
- Showed days until tax-free and warning badge if within 7 days on open positions.
- Added loss alert when unrealised P/L &lt; -10%.
### 2026-03-04 — Afternoon Update (Scheduler & Dashboard polish)

**Agent:** Antigravity (Raptor mini)  
**Session focus:** In‑app background worker, system status page, extended jobs

- Added in‑dashboard APScheduler background worker with daily jobs for IPO scout, calendar refresh, signal generation, portfolio metric updates and price caching.
- Created `refresh_portfolio_metrics()` helper in `utils/db.py` and wired it to scheduler.
- Added job-status dictionary and ⚙️ System page showing last run times plus manual trigger buttons.
- Added price caching job to prefetch market data for tracked companies and open positions.
- Updated dashboard sidebar radio to include System page and manual buttons.

### 2026-03-04 — Session 1 (Setup + Architecture)

**Agent:** Antigravity (Gemini)  
**Session focus:** Project orientation, architecture decisions, incremental scan implementation

| Time (approx) | Event | Files Affected |
|---|---|---|
| 13:12 | Read `master_context_04mar26.md`. Confirmed project status. | — |
| 13:12 | `ollama list` confirmed only `gemma3:1b` installed — mistral:7b missing. Flagged as blocker. | — |
| 13:48 | Provided full step-by-step PowerShell instructions for session setup. | — |
| 13:55 | Ollama + mistral:7b confirmed working. `python -m utils.llm` passed. Test classification returned score 85 for QuantumLeap Inc. | — |
| 13:55 | User ran `python -m agents.ipo_scout --days 30` — scan started, still running at session end (~60 min). | — |
| 14:06 | **Architecture expansion:** User requested IBKR trading agent, backtesting engine, feedback loop, geopolitical correlation, real-time stocks. Full vision now 8 phases. | `PRODUCT_REQUIREMENTS.md` (created) |
| 14:06 | `requirements.txt` restructured with phased commented sections (Phase 1–8). | `requirements.txt` |
| 14:17 | Feedback engine elevated from Phase 8 add-on → **core design principle**. Now listed as pillar #6 in "What is FinTel". Architecture diagram updated with closed-loop feedback flow. | `PRODUCT_REQUIREMENTS.md` |
| 14:26 | **Temporal segmentation methodology added.** Phase 5 (Backtesting) completely rewritten: 7-step process — segment by market regime (1996–present), train per segment, full lookback, relevance analysis, weighted ensemble. 8 named historical regimes defined. | `PRODUCT_REQUIREMENTS.md` |
| 14:33 | **Advisor principles document created.** Behavioural mandate: independent advisor, not yes-man. Key techniques documented: Purged CV, HMM, SHAP, ECE, Kelly, TFT, DSR, PSI, Conformal Prediction. | `ADVISOR_PRINCIPLES.md` (created) |
| 14:33 | **Incremental scan architecture designed and implemented.** Three scan modes: `--historical` (one-time, 365 days), `--incremental` (delta from last scan date), `--days N` (manual). | `utils/db.py`, `agents/ipo_scout.py` |
| 14:33 | New DB tables: `scan_metadata` (stores `last_scan_date`), `scan_runs` (full run log). New functions: `get_last_scan_date()`, `log_scan_run()`. | `utils/db.py` |
| 14:44 | **Session starter prompt created.** Copy-paste block for starting any new AI session. | `SESSION_STARTER.md` (created) |
| 14:44 | **References section in ADVISOR_PRINCIPLES rebuilt** with institutional credentials, publication years, awards. 3 tiers: Nobel, Peer-reviewed, Practitioner. Policy: no blog posts or unverified sources for strategy. | `ADVISOR_PRINCIPLES.md` |
| 15:05 | Evaluated SQLite DB mid-scan. 143+ filings successfully mapped, scored, and saved. Validated that Phase 2 is working properly. Marked Phase 2 complete. | `PRODUCT_REQUIREMENTS.md`, `PROJECT_LOG.md` |
| 16:20 | Added IPO calendar scrape from Yahoo & Nasdaq; caching in separate `ipo_calendar.db`. Dashboard automatically shows expected listing dates; date picker removed. Created `refresh_calendar_for_filings()` and scheduled daily update in `agents/scheduler.py`. Schema migration stems from new column `expected_listing_date`. | `agents/ipo_scout.py`, `utils/db.py`, `dashboard/app.py`, `agents/scheduler.py` |
| 16:45 | Implemented calendar backfill script (`scripts/backfill_calendar.py`) and `get_upcoming_listings()` helper. Added CLI flag `--once` to scheduler for ad-hoc runs. Updated docs accordingly. | `scripts/backfill_calendar.py`, `utils/db.py`, `agents/scheduler.py` |
| 17:10 | Expanded dashboard KPIs (filings, high conviction, target sectors, open positions, upcoming listings). Added upcoming listings loader, score‑trend line chart, and sector heatmap. Refactored page layout accordingly. | `dashboard/app.py` |
| 15:45 | Wrote `migrate_db_v1.py` and safely updated the `fintel.db` `scan_runs` schema. Commenced `ipo_scout --historical` run. | `scripts/migrate_db_v1.py` |
| 16:15 | **Built Phase 3: Signal Analyst:** Implemented technical indicators (`ta`), news sentiment via Mistral 7B (`feedparser`, `utils/llm.py`), and the composite scoring engine. Added `agents/scheduler.py` to automate scanning. | `agents/signal_analyst.py`, `agents/scheduler.py`, `utils/db.py` |

**Session end status:**
- ⏳ `ipo_scout --historical` currently running to populate 365 days of baseline data.
- ✅ Phase 3 (Signal Analyst) code is fully built and tested.
- ⚠️ **Next action required:** Begin Phase 4: Streamlit Dashboard.

---

## PHASE STATUS

| Phase | Name | Status | Notes |
|---|---|---|---|
| 1 | Foundation | ✅ Complete | Python, venv, SQLite, config, logging |
| 2 | IPO Scout | ✅ Complete | Agent built, first scan validating correctly in DB |
| 3 | Signal Analyst | ✅ Complete | Agent built, yfinance, ta, news sentiment, scheduler |
| 4 | Dashboard | 🔄 In Progress | Next up: Streamlit + Plotly |
| 5 | Backtesting Engine | ⬜ Not started | Temporal segmentation, ML training |
| 6 | IBKR Trading Agent | ⬜ Not started | Paper trade first → live |
| 7 | Real-time Stocks + Geopolitics | ⬜ Not started | FinBERT, GDELT |
| 8 | Feedback Engine | ⬜ Not started | MLOps, continuous learning |

---

## FILE INDEX

| File | Purpose | Last Updated |
|---|---|---|
| `master_context_04mar26.md` | Who Shivam is, financial situation, all goals, advisor rules | 2026-03-04 |
| `ADVISOR_PRINCIPLES.md` | How AI must behave, techniques to apply, credentialed references | 2026-03-04 |
| `PRODUCT_REQUIREMENTS.md` | Full 8-phase product vision, architecture, roadmap | 2026-03-04 |
| `SESSION_STARTER.md` | Copy-paste prompt for starting new AI sessions | 2026-03-04 |
| `PROJECT_LOG.md` | This file — events log, phase status, file index | 2026-03-04 |
| `requirements.txt` | Python packages, organised by phase | 2026-03-04 |
| `agents/ipo_scout.py` | IPO Scout agent — 3-mode scanning | 2026-03-04 |
| `utils/db.py` | Database layer — all SQLite operations | 2026-03-04 |
| `utils/llm.py` | Ollama/Mistral wrapper | Feb 2026 |
| `dashboard/app.py` | Streamlit dashboard (Phase 4) | Feb 2026 |
| `config/settings.py` | Personal config (sectors, thresholds, paths) | Feb 2026 |
| `fintel.db` | Live SQLite database | Ongoing |

---

## KEY DECISIONS LOG

| Date | Decision | Reason |
|---|---|---|
| 2026-02 | Use `ta` not `pandas-ta` | pandas-ta incompatible with Python 3.14 |
| 2026-02 | SEC EDGAR full-text search API (not RSS) | RSS returns empty results |
| 2026-03-04 | 8-phase architecture (expanded from 4) | Added IBKR, backtesting, geopolitics, feedback engine |
| 2026-03-04 | Feedback engine = core design principle, not Phase 8 add-on | Self-improvement is the product's key differentiator |
| 2026-03-04 | Temporal segmentation (8 market regimes, 1996–present) | Naive "more data = better" is false in finance — regime-aware training is correct |
| 2026-03-04 | Incremental scan pattern (--historical once, --incremental daily) | Never re-fetch data that already exists — standard production pipeline design |
| 2026-03-04 | Credentialed-only references (Nobel, NeurIPS, peer-reviewed) | Strategy decisions must rest on validated research, not blog posts |

---

*Append new log entries at the top of the LOG section. Never edit past entries.*
