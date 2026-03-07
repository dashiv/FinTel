"""
FinTel Executive Dashboard  v3.0
=================================
Run:  streamlit run dashboard/app.py
Open: http://localhost:8501

Pages:
  🏠 Overview      — KPIs, score trend, sector breakdown
  🔍 IPO Scanner   — All filings with filters
  📈 Pipeline      — New → Watchlist → Portfolio → Closed
  💼 Portfolio     — Open positions, tax clock, P&L
  🔥 Heatmap       — Sector intelligence heatmap
  ⚙️  System       — Scheduler status, manual controls
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from datetime import datetime, timedelta
import yfinance as yf

# ── OPTIONAL IMPORTS (graceful degradation) ───────────────────────────────────

try:
    from agents.ipo_scout import fetch_expected_listing_date, run_scout, refresh_calendar_for_filings
except ImportError:
    fetch_expected_listing_date = None
    run_scout = None
    refresh_calendar_for_filings = None

try:
    from agents.signal_analyst import generate_signals, analyse_company
except ImportError:
    generate_signals = None
    analyse_company = None

try:
    from utils.llm import generate_company_summary
except ImportError:
    generate_company_summary = None

from utils.db import (
    get_connection,
    get_recent_filings,
    get_watchlist,
    get_portfolio,
    get_closed_positions,
    add_to_watchlist,
    remove_from_watchlist,
    get_filing_by_id,
    get_signals_for_ticker,
    init_database,
    get_upcoming_listings,
)

try:
    from utils.db import refresh_portfolio_metrics, get_tracked_companies, set_expected_listing_date
except ImportError:
    refresh_portfolio_metrics = None
    get_tracked_companies = None
    set_expected_listing_date = None

try:
    from utils.db import get_ai_summary, set_ai_summary
except ImportError:
    get_ai_summary = None
    set_ai_summary = None

# ── PAGE CONFIG (must be first Streamlit call) ────────────────────────────────

st.set_page_config(
    page_title="FinTel",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── DARK THEME CSS ────────────────────────────────────────────────────────────

st.markdown("""
<style>
    .stApp { background-color: #0e1117; color: #fafafa; }
    .metric-card {
        background: #1a1d27;
        border: 1px solid #2d3748;
        border-radius: 10px;
        padding: 16px 20px;
        text-align: center;
    }
    .metric-label { font-size: 12px; color: #718096; text-transform: uppercase; letter-spacing: 1px; }
    .metric-value { font-size: 28px; font-weight: 700; color: #f7fafc; margin: 6px 0 2px; }
    .metric-delta-pos { font-size: 13px; color: #68d391; }
    .metric-delta-neg { font-size: 13px; color: #fc8181; }
    .score-high  { color: #68d391; font-weight: 700; }
    .score-med   { color: #f6e05e; font-weight: 600; }
    .score-low   { color: #fc8181; }
    .tax-warning { background: #744210; border-radius: 6px; padding: 4px 10px;
                   color: #fbd38d; font-size: 12px; font-weight: 600; }
    .tax-safe    { background: #1a4a1a; border-radius: 6px; padding: 4px 10px;
                   color: #68d391; font-size: 12px; }
    div[data-testid="stSidebarNav"] { display: none; }
    .stDataFrame { border-radius: 8px; }
</style>
""", unsafe_allow_html=True)


# ── BACKGROUND SCHEDULER ──────────────────────────────────────────────────────

JOB_KEYS = ["scout", "calendar", "signals", "portfolio", "prices", "ai_summaries"]

@st.cache_resource
def get_job_status() -> dict:
    return {k: None for k in JOB_KEYS}

def mark_job(name: str):
    get_job_status()[name] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@st.cache_resource
def start_scheduler():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        sched = BackgroundScheduler(timezone="Europe/Luxembourg")

        if run_scout:
            sched.add_job(
                lambda: (run_scout(days_back=30, min_score=0), mark_job("scout")),
                CronTrigger(hour=6, minute=0),
                id="scout", name="🔍 IPO Scout", replace_existing=True
            )
        if refresh_calendar_for_filings:
            sched.add_job(
                lambda: (refresh_calendar_for_filings(), mark_job("calendar")),
                CronTrigger(hour=7, minute=0),
                id="calendar", name="📅 Calendar Refresh", replace_existing=True
            )
        if generate_signals:
            sched.add_job(
                lambda: (generate_signals(), mark_job("signals")),
                CronTrigger(hour=22, minute=0),
                id="signals", name="📡 Signal Analyst", replace_existing=True
            )
        if refresh_portfolio_metrics:
            sched.add_job(
                lambda: (refresh_portfolio_metrics(), mark_job("portfolio")),
                CronTrigger(hour=22, minute=30),
                id="portfolio", name="📊 Portfolio Metrics", replace_existing=True
            )
        if get_tracked_companies:
            def _cache_prices():
                for c in (get_tracked_companies() or []):
                    if c.get("ticker"):
                        try:
                            yf.Ticker(c["ticker"]).history(period="1mo")
                        except Exception:
                            pass
                mark_job("prices")
            sched.add_job(
                _cache_prices,
                CronTrigger(hour=5, minute=30),
                id="prices", name="💰 Price Cache", replace_existing=True
            )

        # ── Telegram alerts ──────────────────────────────────────────────────
        try:
            from utils.telegram_bot import (
                alert_daily_digest,
                check_and_alert_new_signals,
                alert_portfolio_loss,
                alert_tax_threshold,
            )
            import sqlite3 as _sqlite3

            sched.add_job(
                alert_daily_digest,
                CronTrigger(hour=7, minute=30),
                id="tg_digest", name="📲 Morning Digest", replace_existing=True
            )

            sched.add_job(
                lambda: check_and_alert_new_signals(lookback_minutes=31),
                CronTrigger(hour="7-22", minute="0,30", day_of_week="mon-fri"),
                id="tg_signals", name="📲 Signal Watcher", replace_existing=True
            )

            def _check_portfolio_alerts():
                try:
                    _conn = _sqlite3.connect(os.path.join(ROOT, "fintel.db"))
                    positions = _conn.execute("""
                        SELECT company_name, ticker,
                               buy_price, shares,
                               amount_invested, buy_date
                        FROM portfolio
                        WHERE closed = 0 OR closed IS NULL
                    """).fetchall()
                    _conn.close()

                    for name, ticker, buy_price, shares, invested, buy_date in positions:
                        if not ticker or not buy_price:
                            continue
                        try:
                            import yfinance as _yf
                            hist = _yf.Ticker(ticker).history(period="2d")
                            if not hist.empty:
                                live = float(hist["Close"].iloc[-1])
                                pct  = (live - float(buy_price)) / float(buy_price) * 100
                                if pct < -10:
                                    alert_portfolio_loss(
                                        name, ticker, pct,
                                        float(invested or 0)
                                    )
                        except Exception:
                            pass
                        try:
                            from datetime import datetime as _dt
                            buy_dt    = _dt.strptime(buy_date[:10], "%Y-%m-%d")
                            days_held = (_dt.now() - buy_dt).days
                            remaining = max(0, 183 - days_held)
                            if remaining in [0, 7, 14]:
                                alert_tax_threshold(
                                    name, ticker, days_held, remaining
                                )
                        except Exception:
                            pass
                except Exception:
                    pass

            sched.add_job(
                _check_portfolio_alerts,
                CronTrigger(hour=9, minute=0),
                id="tg_portfolio", name="📲 Portfolio Alerts", replace_existing=True
            )

            def _score_new_daily():
                try:
                    from scripts.score_new_ipos import main as _score_main
                    _score_main(days_back=7, force_rescore=False)
                    mark_job("ai_summaries")
                except Exception:
                    pass

            sched.add_job(
                _score_new_daily,
                CronTrigger(hour=6, minute=30),
                id="tg_scorer", name="🤖 AI Scorer", replace_existing=True
            )

        except ImportError:
            pass  # Telegram optional — never crash dashboard if bot not configured

        sched.start()
        return sched
    except Exception:
        return None


start_scheduler()


# ── CACHED DATA LOADERS ───────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_filings(days: int, min_score: int) -> list:
    try:
        init_database()
        return get_recent_filings(days=days, min_score=min_score) or []
    except Exception:
        return []

@st.cache_data(ttl=300)
def load_watchlist_data(min_score: int = 0) -> list:
    try:
        return get_watchlist(min_score) or []
    except Exception:
        return []

@st.cache_data(ttl=300)
def load_portfolio_data() -> list:
    try:
        return get_portfolio() or []
    except Exception:
        return []

@st.cache_data(ttl=300)
def load_closed_data() -> list:
    try:
        return get_closed_positions() or []
    except Exception:
        return []

@st.cache_data(ttl=300)
def load_upcoming(days: int = 90) -> list:
    try:
        return get_upcoming_listings(days) or []
    except Exception:
        return []

@st.cache_data(ttl=60)
def fetch_live_price(ticker: str):
    if not ticker:
        return None
    try:
        h = yf.Ticker(ticker).history(period="2d")
        if not h.empty:
            return float(h["Close"].iloc[-1])
    except Exception:
        pass
    return None


# ── HELPERS ───────────────────────────────────────────────────────────────────

def score_badge(score) -> str:
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "<span style='color:#718096'>N/A</span>"
    if s >= 75:
        return f"<span class='score-high'>{s:.0f}</span>"
    if s >= 55:
        return f"<span class='score-med'>{s:.0f}</span>"
    return f"<span class='score-low'>{s:.0f}</span>"

def days_held_badge(buy_date_str: str) -> str:
    try:
        buy_dt    = datetime.strptime(buy_date_str[:10], "%Y-%m-%d")
        days      = (datetime.now() - buy_dt).days
        remaining = max(0, 183 - days)
        if remaining == 0:
            return f"<span class='tax-safe'>✅ Tax-free ({days}d held)</span>"
        if remaining <= 14:
            return f"<span class='tax-warning'>⚠ {remaining}d to tax-free</span>"
        return f"<span style='color:#a0aec0'>{days}d held | {remaining}d to go</span>"
    except Exception:
        return ""

def pl_str(pct, eur=None) -> str:
    if pct is None:
        return "—"
    color = "#68d391" if pct >= 0 else "#fc8181"
    base  = f"<span style='color:{color};font-weight:600'>{pct:+.1f}%</span>"
    if eur is not None:
        base += f" <span style='color:{color}'>({eur:+.0f}€)</span>"
    return base


# ── SIDEBAR NAVIGATION ────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🧠 FinTel")
    st.markdown("*AI-powered IPO intelligence*")
    st.divider()

    PAGES = [
        "🏠 Overview",
        "🔍 IPO Scanner",
        "📈 Pipeline",
        "💼 Portfolio",
        "🔥 Heatmap",
        "⚙️ System",
    ]

    if "page" not in st.session_state:
        st.session_state.page = "🏠 Overview"

    if st.session_state.get("detail_id"):
        if st.button("⟵ Back to Scanner"):
            st.session_state.pop("detail_id", None)
            st.session_state.page = "🔍 IPO Scanner"
            st.rerun()
        st.info("Viewing company detail")
    else:
        for p in PAGES:
            is_active = st.session_state.page == p
            if st.button(p, key=f"nav_{p}", use_container_width=True,
                         type="primary" if is_active else "secondary"):
                st.session_state.page = p
                st.rerun()

    st.divider()
    st.markdown("**Filters**")
    days_filter  = st.selectbox("Time window", [30, 60, 90, 180, 365], index=1)
    score_filter = st.slider("Min score", 0, 100, 50)

    st.divider()
    st.caption(f"Refreshed: {datetime.now().strftime('%H:%M:%S')}")
    if st.button("🔄 Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


# ── COMPANY DETAIL PAGE ───────────────────────────────────────────────────────

def page_company_detail(filing_id: int):
    filing = get_filing_by_id(filing_id)
    if not filing:
        st.error("Company not found.")
        if st.button("⟵ Back"):
            st.session_state.pop("detail_id", None)
            st.rerun()
        return

    name   = filing.get("company_name", "Unknown")
    ticker = filing.get("ticker", "")
    score  = filing.get("interest_score") or filing.get("score")
    sector = filing.get("primary_sector") or filing.get("sector", "—")

    st.title(f"🏢 {name}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Sector",      sector)
    c2.metric("Score",       f"{score:.0f}" if score else "N/A")
    c3.metric("Filing Type", filing.get("filing_type", "—"))
    c4.metric("Filed",       (filing.get("filing_date") or "")[:10])

    # Expected listing
    exp = filing.get("expected_listing_date")
    if exp:
        st.info(f"📅 Expected listing: **{exp[:10]}**")
    elif fetch_expected_listing_date:
        if st.button("🔄 Check IPO calendars for listing date"):
            with st.spinner("Querying calendars..."):
                found = fetch_expected_listing_date(name)
            if found:
                if set_expected_listing_date:
                    set_expected_listing_date(filing_id, found)
                st.success(f"Found: {found[:10]}")
                st.cache_data.clear()
                st.rerun()
            else:
                st.info("Not found yet — scheduler will keep checking.")

    st.divider()

    tab_chart, tab_ai, tab_signals, tab_info = st.tabs(
        ["📊 Price Chart", "🧠 AI Summary", "📡 Signals", "📄 Filing Info"]
    )

    # ── Price Chart
    with tab_chart:
        if ticker:
            period = st.radio(
                "Period", ["1mo", "3mo", "6mo", "1y", "2y"],
                horizontal=True, index=2, key="det_period"
            )
            try:
                hist = yf.Ticker(ticker).history(period=period, auto_adjust=True)
                if not hist.empty:
                    hist.reset_index(inplace=True)
                    try:
                        hist["Date"] = hist["Date"].dt.tz_localize(None)
                    except Exception:
                        try:
                            hist["Date"] = hist["Date"].dt.tz_convert(None)
                        except Exception:
                            pass

                    fig = go.Figure()
                    fig.add_trace(go.Candlestick(
                        x=hist["Date"],
                        open=hist["Open"], high=hist["High"],
                        low=hist["Low"],   close=hist["Close"],
                        name=ticker,
                        increasing_line_color="#68d391",
                        decreasing_line_color="#fc8181",
                    ))
                    fig.add_trace(go.Bar(
                        x=hist["Date"], y=hist["Volume"],
                        name="Volume", yaxis="y2",
                        marker_color="rgba(100,149,237,0.3)",
                    ))
                    fig.update_layout(
                        height=460, paper_bgcolor="#0e1117",
                        plot_bgcolor="#0e1117", font_color="#fafafa",
                        xaxis=dict(gridcolor="#2d3748", rangeslider_visible=False),
                        yaxis=dict(gridcolor="#2d3748", title="Price ($)"),
                        yaxis2=dict(overlaying="y", side="right",
                                    showgrid=False, title="Volume"),
                        legend=dict(orientation="h", y=1.05),
                        margin=dict(l=0, r=0, t=30, b=0),
                    )
                    st.plotly_chart(fig, use_container_width=True)

                    latest = hist.iloc[-1]
                    first  = hist.iloc[0]
                    ret    = (float(latest["Close"]) - float(first["Close"])) / float(first["Close"])
                    s1, s2, s3, s4 = st.columns(4)
                    s1.metric("Current",       f"${float(latest['Close']):.2f}")
                    s2.metric("Period Return",  f"{ret:+.1%}")
                    s3.metric("Period High",    f"${hist['High'].max():.2f}")
                    s4.metric("Period Low",     f"${hist['Low'].min():.2f}")
                else:
                    st.info("No price data available yet.")
            except Exception as e:
                st.warning(f"Could not load price data: {e}")
        else:
            st.info("No ticker identified yet — price chart unavailable until the company lists.")

    # ── AI Summary
    with tab_ai:
        existing = get_ai_summary(filing_id) if get_ai_summary else None
        if existing:
            st.markdown("### 🧠 AI Analysis")
            st.markdown(existing)
        else:
            st.info("No AI summary generated yet.")

        if generate_company_summary and set_ai_summary:
            if st.button("🧠 Generate AI Summary", key=f"gen_{filing_id}"):
                with st.spinner("Analysing filing with AI..."):
                    try:
                        summary = generate_company_summary(filing)
                        set_ai_summary(filing_id, summary)
                        st.success("Summary generated!")
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"AI summary failed: {e}")

    # ── Signals
    with tab_signals:
        if ticker:
            signals = get_signals_for_ticker(ticker) or []
            if signals:
                sig_df = pd.DataFrame(signals)
                if "signal_date" in sig_df.columns:
                    sig_df = sig_df.sort_values("signal_date", ascending=False)
                st.dataframe(sig_df, use_container_width=True, hide_index=True)
            else:
                st.info("No signals yet.")
                if analyse_company and st.button("📡 Run Signal Analysis Now"):
                    with st.spinner("Running..."):
                        try:
                            analyse_company(ticker)
                            st.success("Done!")
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed: {e}")
        else:
            st.info("No ticker available yet.")

    # ── Filing Info
    with tab_info:
        display_keys = [
            "cik", "filing_type", "filing_date",
            "sic_code", "sic_description",
            "state_of_incorporation", "sector_rationale",
        ]
        rows = [(k, str(filing.get(k, "—"))) for k in display_keys if k in filing]
        if rows:
            st.dataframe(
                pd.DataFrame(rows, columns=["Field", "Value"]),
                use_container_width=True, hide_index=True
            )
        sec_url = filing.get("sec_filing_url") or filing.get("filing_url")
        if sec_url:
            st.link_button("📄 View SEC Filing", sec_url)

    # ── Watchlist action
    st.divider()
    wl     = load_watchlist_data()
    wl_ids = [w.get("id") or w.get("filing_id") for w in wl]
    in_wl  = filing_id in wl_ids

    ca, cb = st.columns(2)
    with ca:
        if in_wl:
            if st.button("➖ Remove from Watchlist", type="secondary"):
                remove_from_watchlist(filing_id)
                st.cache_data.clear()
                st.rerun()
        else:
            if st.button("⭐ Add to Watchlist", type="primary"):
                add_to_watchlist(filing_id)
                st.cache_data.clear()
                st.rerun()
    with cb:
        if st.button("⟵ Back to Scanner"):
            st.session_state.pop("detail_id", None)
            st.session_state.page = "🔍 IPO Scanner"
            st.rerun()


# ── PAGE: OVERVIEW ────────────────────────────────────────────────────────────

def page_overview():
    st.title("🏠 FinTel Overview")
    st.caption(f"As of {datetime.now().strftime('%d %b %Y, %H:%M CET')}")

    filings   = load_filings(days_filter, 0)
    portfolio = load_portfolio_data()
    watchlist = load_watchlist_data()
    upcoming  = load_upcoming(90)

    high_conv = [f for f in filings if (f.get("interest_score") or 0) >= 75]
    open_pos  = [p for p in portfolio if not p.get("closed")]

    # KPI row
    k1, k2, k3, k4, k5 = st.columns(5)
    for col, label, val, sub in [
        (k1, "📋 Filings Scanned",  str(len(filings)),   f"Last {days_filter}d"),
        (k2, "🎯 High Conviction",   str(len(high_conv)), "Score ≥ 75"),
        (k3, "⭐ Watchlist",         str(len(watchlist)), "Tracked"),
        (k4, "💼 Open Positions",    str(len(open_pos)),  "Active trades"),
        (k5, "📅 Upcoming Listings", str(len(upcoming)),  "Next 90 days"),
    ]:
        with col:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">{label}</div>
                <div class="metric-value">{val}</div>
                <div class="metric-delta-pos">{sub}</div>
            </div>""", unsafe_allow_html=True)

    st.divider()
    left, right = st.columns([2, 1])

    # Score trend
    with left:
        st.subheader("📈 Score Trend")
        if filings:
            df_f      = pd.DataFrame(filings)
            sc_col    = "interest_score" if "interest_score" in df_f.columns else "score"
            dt_col    = "filing_date"
            if sc_col in df_f.columns and dt_col in df_f.columns:
                df_f[dt_col] = pd.to_datetime(df_f[dt_col], errors="coerce")
                df_f         = df_f.dropna(subset=[dt_col, sc_col])
                df_f["week"] = df_f[dt_col].dt.to_period("W").dt.start_time
                weekly       = df_f.groupby("week")[sc_col].mean().reset_index()
                fig = go.Figure(go.Scatter(
                    x=weekly["week"], y=weekly[sc_col],
                    mode="lines+markers",
                    line=dict(color="#667eea", width=2),
                    fill="tozeroy", fillcolor="rgba(102,126,234,0.15)",
                ))
                fig.add_hline(y=75, line_dash="dash", line_color="#68d391",
                              annotation_text="High conviction")
                fig.update_layout(
                    height=290, paper_bgcolor="#0e1117",
                    plot_bgcolor="#0e1117", font_color="#fafafa",
                    xaxis=dict(gridcolor="#2d3748"),
                    yaxis=dict(gridcolor="#2d3748", range=[0, 100]),
                    margin=dict(l=0, r=0, t=10, b=0), showlegend=False,
                )
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No filings yet. Run the IPO scout first.")

    # Sector pie
    with right:
        st.subheader("🥧 Sectors")
        if filings:
            df_s    = pd.DataFrame(filings)
            sec_col = "primary_sector" if "primary_sector" in df_s.columns else "sector"
            if sec_col in df_s.columns:
                counts = (df_s[sec_col].fillna("Unknown")
                          .value_counts().head(8).reset_index())
                counts.columns = ["sector", "count"]
                fig_pie = px.pie(
                    counts, values="count", names="sector",
                    color_discrete_sequence=px.colors.sequential.Plasma_r,
                    hole=0.4,
                )
                fig_pie.update_layout(
                    height=290, paper_bgcolor="#0e1117",
                    font_color="#fafafa",
                    margin=dict(l=0, r=0, t=0, b=0),
                    legend=dict(font_size=10),
                )
                fig_pie.update_traces(textposition="inside", textinfo="percent")
                st.plotly_chart(fig_pie, use_container_width=True)

    # Upcoming listings
    if upcoming:
        st.divider()
        st.subheader("📅 Upcoming Listings")
        st.dataframe(pd.DataFrame(upcoming), use_container_width=True, hide_index=True)

    # High conviction list
    if high_conv:
        st.divider()
        st.subheader("🎯 Recent High Conviction")
        for f in high_conv[:5]:
            fid  = f.get("id")
            name = f.get("company_name", "Unknown")
            c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
            c1.markdown(
                f"**{name}** "
                f"<span style='color:#a0aec0;font-size:12px'>"
                f"{f.get('primary_sector') or f.get('sector','—')}</span>",
                unsafe_allow_html=True,
            )
            c2.markdown(score_badge(f.get("interest_score") or f.get("score")),
                        unsafe_allow_html=True)
            c3.write((f.get("filing_date") or "")[:10])
            if fid and c4.button("View →", key=f"ov_{fid}"):
                st.session_state["detail_id"] = int(fid)
                st.rerun()


# ── PAGE: IPO SCANNER ─────────────────────────────────────────────────────────

def page_scanner():
    st.title("🔍 IPO Scanner")
    filings = load_filings(days_filter, score_filter)

    if not filings:
        st.info(f"No filings with score ≥ {score_filter} in the last {days_filter} days.")
        if run_scout and st.button("▶ Run IPO Scout Now"):
            with st.spinner("Scanning SEC EDGAR..."):
                try:
                    run_scout(days_back=days_filter, min_score=0)
                    st.cache_data.clear()
                    st.success("Done!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Scout failed: {e}")
        return

    df      = pd.DataFrame(filings)
    sc_col  = "interest_score" if "interest_score" in df.columns else "score"
    sec_col = "primary_sector"  if "primary_sector"  in df.columns else "sector"

    f1, f2, f3 = st.columns(3)
    sectors    = ["All"] + sorted(df[sec_col].dropna().unique().tolist()) if sec_col in df.columns else ["All"]
    sel_sector = f1.selectbox("Sector", sectors)
    sel_type   = f2.selectbox("Filing Type", ["All", "S-1", "F-1"])
    sort_by    = f3.selectbox("Sort by", ["Score ↓", "Date ↓", "Company ↑"])

    if sel_sector != "All" and sec_col in df.columns:
        df = df[df[sec_col] == sel_sector]
    if sel_type != "All" and "filing_type" in df.columns:
        df = df[df["filing_type"] == sel_type]
    if sort_by == "Score ↓" and sc_col in df.columns:
        df = df.sort_values(sc_col, ascending=False)
    elif sort_by == "Date ↓" and "filing_date" in df.columns:
        df = df.sort_values("filing_date", ascending=False)
    elif sort_by == "Company ↑" and "company_name" in df.columns:
        df = df.sort_values("company_name")

    st.caption(f"{len(df)} filings")

    for _, row in df.iterrows():
        fid    = row.get("id")
        name   = row.get("company_name", "Unknown")
        score  = row.get(sc_col)
        sector = row.get(sec_col, "—") or "—"
        fdate  = str(row.get("filing_date") or "")[:10]
        ftype  = row.get("filing_type", "")
        ticker = row.get("ticker", "")

        c1, c2, c3, c4, c5 = st.columns([3, 1, 1, 1, 1])
        c1.markdown(
            f"**{name}** "
            f"<span style='color:#a0aec0;font-size:12px'>{sector}</span>"
            + (f"  `{ticker}`" if ticker else ""),
            unsafe_allow_html=True,
        )
        c2.markdown(score_badge(score), unsafe_allow_html=True)
        c3.write(ftype)
        c4.write(fdate)
        if fid and c5.button("View", key=f"sc_{fid}"):
            st.session_state["detail_id"] = int(fid)
            st.rerun()

        st.markdown(
            "<hr style='border:0;border-top:1px solid #2d3748;margin:4px 0'>",
            unsafe_allow_html=True,
        )


# ── PAGE: PIPELINE ────────────────────────────────────────────────────────────

def page_pipeline():
    st.title("📈 IPO Pipeline")
    tab_new, tab_wl, tab_open, tab_closed = st.tabs(
        ["🆕 New Filings", "⭐ Watchlist", "💼 Open Positions", "✅ Closed Trades"]
    )

    with tab_new:
        filings = load_filings(days_filter, score_filter)
        if not filings:
            st.info("No filings. Adjust filters or run the scout.")
            return
        sc_col  = "interest_score" if filings and "interest_score" in filings[0] else "score"
        sec_col = "primary_sector" if filings and "primary_sector" in filings[0] else "sector"
        for f in filings[:50]:
            fid  = f.get("id")
            name = f.get("company_name", "Unknown")
            c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
            c1.markdown(
                f"**{name}** "
                f"<span style='color:#a0aec0;font-size:12px'>"
                f"{f.get(sec_col,'—') or '—'}</span>",
                unsafe_allow_html=True,
            )
            c2.markdown(score_badge(f.get(sc_col)), unsafe_allow_html=True)
            c3.write(str(f.get("filing_date",""))[:10])
            if fid:
                col_a, col_b = c4.columns(2)
                if col_a.button("⭐", key=f"pw_{fid}", help="Add to watchlist"):
                    add_to_watchlist(fid)
                    st.cache_data.clear()
                    st.rerun()
                if col_b.button("→", key=f"pd_{fid}", help="View detail"):
                    st.session_state["detail_id"] = int(fid)
                    st.rerun()

    with tab_wl:
        watchlist = load_watchlist_data()
        if not watchlist:
            st.info("Watchlist is empty.")
            return
        sc_col  = "interest_score" if watchlist and "interest_score" in watchlist[0] else "score"
        sec_col = "primary_sector" if watchlist and "primary_sector" in watchlist[0] else "sector"
        for w in watchlist:
            fid  = w.get("id") or w.get("filing_id")
            name = w.get("company_name", "Unknown")
            c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
            c1.markdown(
                f"**{name}** "
                f"<span style='color:#a0aec0;font-size:12px'>"
                f"{w.get(sec_col,'—') or '—'}</span>",
                unsafe_allow_html=True,
            )
            c2.markdown(score_badge(w.get(sc_col)), unsafe_allow_html=True)
            if fid:
                if c3.button("➖", key=f"wr_{fid}", help="Remove"):
                    remove_from_watchlist(fid)
                    st.cache_data.clear()
                    st.rerun()
                if c4.button("→", key=f"wd_{fid}", help="Detail"):
                    st.session_state["detail_id"] = int(fid)
                    st.rerun()

    with tab_open:
        portfolio = load_portfolio_data()
        open_pos  = [p for p in portfolio if not p.get("closed")]
        if not open_pos:
            st.info("No open positions.")
            return
        total_inv = sum(float(p.get("amount_invested") or 0) for p in open_pos)
        total_pl  = 0.0
        for pos in open_pos:
            ticker    = pos.get("ticker", "")
            name      = pos.get("company_name", ticker or "Unknown")
            buy_price = float(pos.get("buy_price") or 0)
            shares    = float(pos.get("shares") or 0)
            invested  = float(pos.get("amount_invested") or buy_price * shares)
            buy_date  = pos.get("buy_date") or pos.get("purchase_date", "")
            live      = fetch_live_price(ticker) if ticker else None
            pct = eur = None
            if live and buy_price:
                pct = (live - buy_price) / buy_price * 100
                eur = (live - buy_price) * shares
                total_pl += eur
            with st.expander(
                f"{'🔴 ' if pct and pct < -10 else ''}{name} ({ticker})",
                expanded=False
            ):
                r1, r2, r3, r4 = st.columns(4)
                r1.metric("Buy",      f"${buy_price:.2f}" if buy_price else "—")
                r2.metric("Now",      f"${live:.2f}" if live else "N/A")
                r3.metric("Invested", f"€{invested:.0f}")
                r4.metric("Shares",   f"{shares:.0f}")
                st.markdown(
                    f"**P&L:** {pl_str(pct, eur)}&nbsp;&nbsp;"
                    f"**Tax:** {days_held_badge(buy_date)}",
                    unsafe_allow_html=True,
                )
                if pct and pct < -10:
                    st.error(f"⚠️ Down {pct:.1f}% — review stop-loss")
        st.divider()
        m1, m2 = st.columns(2)
        m1.metric("Total Invested", f"€{total_inv:,.0f}")
        m2.metric("Unrealised P&L", f"€{total_pl:+,.0f}",
                  delta=f"{total_pl/total_inv*100:+.1f}%" if total_inv else None)

    with tab_closed:
        closed = load_closed_data()
        if not closed:
            st.info("No closed trades yet.")
            return
        total_pl = 0.0
        winners  = 0
        for pos in closed:
            bp = float(pos.get("buy_price")  or 0)
            sp = float(pos.get("sell_price") or 0)
            sh = float(pos.get("shares")     or 0)
            pct = eur = None
            if bp and sp and sh:
                pct = (sp - bp) / bp * 100
                eur = (sp - bp) * sh
                total_pl += eur
                if pct > 0:
                    winners += 1
            c1, c2, c3 = st.columns([3, 2, 1])
            c1.write(pos.get("company_name", "Unknown"))
            c2.markdown(pl_str(pct, eur), unsafe_allow_html=True)
            c3.write(str(pos.get("sell_date", ""))[:10])
        st.divider()
        n = len(closed)
        m1, m2, m3 = st.columns(3)
        m1.metric("Closed Trades", str(n))
        m2.metric("Win Rate",      f"{winners/n*100:.0f}%" if n else "—")
        m3.metric("Total P&L",     f"€{total_pl:+,.0f}")


# ── PAGE: PORTFOLIO ───────────────────────────────────────────────────────────

def page_portfolio():
    st.title("💼 Portfolio Manager")

    portfolio = load_portfolio_data()
    closed    = load_closed_data()
    open_pos  = [p for p in portfolio if not p.get("closed")]

    if not open_pos and not closed:
        st.info("Portfolio is empty. Add positions from the Pipeline page.")
        return

    if closed:
        st.subheader("📊 Performance Summary")
        total_pl  = total_inv = 0.0
        winners   = 0
        for pos in closed:
            bp  = float(pos.get("buy_price")  or 0)
            sp  = float(pos.get("sell_price") or 0)
            sh  = float(pos.get("shares")     or 0)
            amt = float(pos.get("amount_invested") or bp * sh)
            if bp and sp and sh:
                total_pl  += (sp - bp) * sh
                total_inv += amt
                if sp > bp:
                    winners += 1
        n = len(closed)
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Closed Trades", str(n))
        k2.metric("Win Rate",      f"{winners/n*100:.0f}%" if n else "—")
        k3.metric("Avg Return",    f"{total_pl/total_inv*100:+.1f}%" if total_inv else "—")
        k4.metric("Total P&L",     f"€{total_pl:+,.0f}")
        st.divider()

    if open_pos:
        st.subheader("📈 Open Positions")
        total_inv = total_unreal = 0.0
        for pos in open_pos:
            ticker    = pos.get("ticker", "")
            name      = pos.get("company_name", ticker or "Unknown")
            buy_price = float(pos.get("buy_price") or 0)
            shares    = float(pos.get("shares")    or 0)
            invested  = float(pos.get("amount_invested") or buy_price * shares)
            buy_date  = pos.get("buy_date") or pos.get("purchase_date", "")
            total_inv += invested
            live = fetch_live_price(ticker) if ticker else None
            pct = eur = None
            if live and buy_price:
                pct = (live - buy_price) / buy_price * 100
                eur = (live - buy_price) * shares
                total_unreal += eur
            alert = pct is not None and pct < -10
            with st.expander(
                f"{'🔴 ' if alert else '🟢 '}{name} ({ticker})"
                + (f"  {pct:+.1f}%" if pct is not None else ""),
                expanded=alert,
            ):
                c1, c2, c3 = st.columns(3)
                c1.metric("Buy Price", f"${buy_price:.2f}" if buy_price else "—")
                c2.metric("Now",       f"${live:.2f}" if live else "Unavailable")
                c3.metric("Invested",  f"€{invested:.0f}")
                st.markdown(
                    f"**Unrealised P&L:** {pl_str(pct, eur)}<br>"
                    f"**Tax clock:** {days_held_badge(buy_date)}",
                    unsafe_allow_html=True,
                )
                if alert:
                    st.error(f"⚠️ Down {pct:.1f}% — review stop-loss")

        st.divider()
        pa, pb = st.columns(2)
        pa.metric("Total Deployed",  f"€{total_inv:,.0f}")
        pb.metric("Unrealised P&L",  f"€{total_unreal:+,.0f}",
                  delta=f"{total_unreal/total_inv*100:+.1f}%" if total_inv else None)
        st.progress(
            min(1.0, total_inv / 3000),
            text=f"Capital deployed: €{total_inv:.0f} / €3,000  "
                 f"(€{max(0, 3000 - total_inv):.0f} available)"
        )


# ── PAGE: HEATMAP ─────────────────────────────────────────────────────────────

def page_heatmap():
    st.title("🔥 Sector Intelligence Heatmap")
    st.caption("Which sectors produce the most signals and highest scores")

    try:
        conn      = get_connection()
        col_info  = conn.execute("PRAGMA table_info(ipo_filings)").fetchall()
        col_names = [c[1] for c in col_info]
        sec_col   = "primary_sector" if "primary_sector" in col_names else (
                    "sector" if "sector" in col_names else None)
        sc_col    = "interest_score" if "interest_score" in col_names else (
                    "score" if "score" in col_names else None)

        if not sec_col or not sc_col:
            st.warning("Sector or score columns not found in the database.")
            conn.close()
            return

        sector_df = pd.read_sql(f"""
            SELECT
                COALESCE({sec_col}, 'Unclassified') AS sector,
                COUNT(*) AS total_filings,
                ROUND(AVG({sc_col}), 1) AS avg_score,
                SUM(CASE WHEN {sc_col} >= 75 THEN 1 ELSE 0 END) AS high_conviction,
                SUM(CASE WHEN {sc_col} >= 55 THEN 1 ELSE 0 END) AS medium_conviction,
                MAX(filing_date) AS latest_filing
            FROM ipo_filings
            WHERE {sec_col} IS NOT NULL
              AND filing_date >= date('now', '-{days_filter} days')
            GROUP BY {sec_col}
            ORDER BY high_conviction DESC
            LIMIT 20
        """, conn)

        score_dist = pd.read_sql(f"""
            SELECT COALESCE({sec_col}, 'Unclassified') AS sector,
                   {sc_col} AS score
            FROM ipo_filings
            WHERE {sec_col} IS NOT NULL AND {sc_col} IS NOT NULL
              AND filing_date >= date('now', '-365 days')
        """, conn)
        conn.close()
    except Exception as e:
        st.error(f"Could not load sector data: {e}")
        return

    if sector_df.empty:
        st.info("No sector data yet. Run the IPO scout to populate.")
        return

    hot_sectors = sector_df[sector_df["avg_score"] >= 70]

    m1, m2, m3 = st.columns(3)
    m1.metric("Sectors Tracked",   str(len(sector_df)))
    m2.metric("Hottest Sector",    sector_df.iloc[0]["sector"],
              f"{int(sector_df.iloc[0]['high_conviction'])} HC signals")
    m3.metric("Hot Sectors (≥70)", str(len(hot_sectors)))

    st.divider()
    col_bar, col_table = st.columns([3, 2])

    with col_bar:
        st.subheader(f"Signal Density — Last {days_filter} Days")
        fig = px.bar(
            sector_df.sort_values("high_conviction", ascending=True),
            x="high_conviction", y="sector", orientation="h",
            color="avg_score",
            color_continuous_scale="RdYlGn",
            range_color=[40, 85],
            text="high_conviction",
            labels={
                "high_conviction": "High Conviction Signals (≥75)",
                "sector": "Sector", "avg_score": "Avg Score",
            },
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(
            height=max(350, len(sector_df) * 28),
            paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
            font_color="#fafafa",
            xaxis=dict(gridcolor="#2d3748"),
            yaxis=dict(gridcolor="#2d3748"),
            coloraxis_colorbar=dict(title="Avg Score", tickfont_size=10),
            margin=dict(l=0, r=40, t=10, b=0),
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_table:
        st.subheader("Sector Scorecard")
        display = sector_df[[
            "sector", "total_filings", "avg_score",
            "high_conviction", "medium_conviction"
        ]].rename(columns={
            "total_filings": "Total", "avg_score": "Avg Score",
            "high_conviction": "HC (≥75)", "medium_conviction": "MC (≥55)",
        })

        def colour_score(val):
            try:
                v = float(val)
                if v >= 75: return "background-color:#1a4a1a;color:#7fff7f"
                if v >= 60: return "background-color:#3a3a00;color:#ffff88"
                return "background-color:#3a0000;color:#ff8888"
            except Exception:
                return ""

        st.dataframe(
            display.style.applymap(colour_score, subset=["Avg Score"]),
            use_container_width=True, hide_index=True,
            height=min(500, len(sector_df) * 38 + 40),
        )

    if not score_dist.empty and len(score_dist) >= 20:
        st.divider()
        st.subheader("Score Distribution by Sector — Last 12 Months")
        top12 = (score_dist.groupby("sector")["score"]
                 .count().nlargest(12).index)
        fig_box = px.box(
            score_dist[score_dist["sector"].isin(top12)],
            x="sector", y="score", color="sector",
            points="outliers",
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig_box.update_layout(
            height=380, showlegend=False,
            paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
            font_color="#fafafa",
            xaxis=dict(gridcolor="#2d3748", tickangle=-35),
            yaxis=dict(gridcolor="#2d3748", range=[0, 105]),
            margin=dict(l=0, r=0, t=10, b=80),
        )
        fig_box.add_hline(
            y=75, line_dash="dash", line_color="#68d391",
            annotation_text="High conviction (75)",
            annotation_font_color="#68d391",
        )
        st.plotly_chart(fig_box, use_container_width=True)

    if not hot_sectors.empty:
        st.divider()
        st.subheader("🚨 Hot Sectors Right Now")
        for _, row in hot_sectors.iterrows():
            st.success(
                f"**{row['sector']}** — "
                f"{int(row['high_conviction'])} high-conviction signals | "
                f"avg score {row['avg_score']} | "
                f"latest: {str(row['latest_filing'] or '')[:10]}"
            )


# ── PAGE: SYSTEM ──────────────────────────────────────────────────────────────

def page_system():
    st.title("⚙️ System Status")
    job_status = get_job_status()

    st.subheader("🕐 Scheduled Jobs")

    def _trigger_to_human(trigger_str: str) -> str:
        """Convert APScheduler trigger string to readable schedule."""
        t = str(trigger_str)
        try:
            import re
            h = re.search(r"hour='([^']+)'", t)
            m = re.search(r"minute='([^']+)'", t)
            d = re.search(r"day_of_week='([^']+)'", t)
            hour   = h.group(1) if h else "?"
            minute = m.group(1) if m else "00"
            day    = d.group(1) if d else None
            minute = minute.zfill(2) if minute.isdigit() else minute
            if day:
                return f"Every 30min · {hour}:00–22:00 · Mon–Fri"
            if "-" not in hour and "," not in hour:
                return f"Daily {hour.zfill(2)}:{minute} CET"
            return t
        except Exception:
            return t

    sched      = start_scheduler()
    job_status = get_job_status()
    rows       = []

    if sched:
        try:
            for job in sched.get_jobs():
                next_run = job.next_run_time
                last_ran = job_status.get(job.id)
                rows.append({
                    "Job":        job.name or job.id,
                    "Schedule":   _trigger_to_human(job.trigger),
                    "Next Run":   next_run.strftime("%a %d %b · %H:%M CET") if next_run else "⏸ Paused",
                    "Last Ran":   last_ran if last_ran else "—",
                    "Status":     "✅ Ran" if last_ran else "⏳ Waiting",
                })
        except Exception:
            pass

    if rows:
        df_jobs = pd.DataFrame(rows)
        st.dataframe(
            df_jobs,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Job":      st.column_config.TextColumn("Job",      width="medium"),
                "Schedule": st.column_config.TextColumn("Schedule", width="medium"),
                "Next Run": st.column_config.TextColumn("Next Run", width="medium"),
                "Last Ran": st.column_config.TextColumn("Last Ran", width="medium"),
                "Status":   st.column_config.TextColumn("Status",   width="small"),
            }
        )
        st.caption(f"{len(rows)} jobs active · auto-refreshes on page load")
    else:
        st.warning("⚠️ Scheduler not running. Restart the dashboard.")

    # ── rest of page_system() continues below (manual controls, DB stats etc.)

    st.divider()
    st.subheader("▶ Manual Controls")
    c1, c2, c3 = st.columns(3)

    with c1:
        if run_scout and st.button("▶ Run IPO Scout", use_container_width=True):
            with st.spinner("Scanning..."):
                try:
                    run_scout(days_back=days_filter, min_score=0)
                    mark_job("scout")
                    st.cache_data.clear()
                    st.success("Scout complete!")
                except Exception as e:
                    st.error(f"Failed: {e}")

        if generate_signals and st.button("▶ Run Signals", use_container_width=True):
            with st.spinner("Generating..."):
                try:
                    generate_signals()
                    mark_job("signals")
                    st.cache_data.clear()
                    st.success("Done!")
                except Exception as e:
                    st.error(f"Failed: {e}")

    with c2:
        if refresh_calendar_for_filings and st.button("▶ Refresh Calendar",
                                                       use_container_width=True):
            with st.spinner("Refreshing..."):
                try:
                    refresh_calendar_for_filings()
                    mark_job("calendar")
                    st.cache_data.clear()
                    st.success("Done!")
                except Exception as e:
                    st.error(f"Failed: {e}")

        if refresh_portfolio_metrics and st.button("▶ Portfolio Metrics",
                                                    use_container_width=True):
            with st.spinner("Updating..."):
                try:
                    refresh_portfolio_metrics()
                    mark_job("portfolio")
                    st.success("Done!")
                except Exception as e:
                    st.error(f"Failed: {e}")

    with c3:
        if st.button("📊 30d Win Rate", use_container_width=True):
            try:
                conn = get_connection()
                res  = conn.execute("""
                    SELECT COUNT(*) as total,
                           SUM(CASE WHEN actual_return > 0 THEN 1 ELSE 0 END) as winners
                    FROM signals
                    WHERE signal_date >= date('now', '-30 days')
                      AND actual_return IS NOT NULL
                """).fetchone()
                conn.close()
                if res and res[0]:
                    st.metric("30d Signal Win Rate", f"{res[1]/res[0]*100:.1f}%",
                              help=f"{res[1]}/{res[0]} signals profitable")
                else:
                    st.info("No resolved signals yet.")
            except Exception as e:
                st.warning(f"Could not compute: {e}")

        if st.button("🗑 Clear Cache", use_container_width=True):
            st.cache_data.clear()
            st.success("Cache cleared.")

    st.divider()
    st.subheader("📦 Database Stats")
    try:
        conn = get_connection()
        for tbl in ["ipo_filings", "watchlist", "portfolio", "signals"]:
            try:
                n = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                st.write(f"**{tbl}**: {n:,} rows")
            except Exception:
                pass
        conn.close()
    except Exception as e:
        st.warning(f"Could not read DB: {e}")

    st.divider()
    st.subheader("🚀 Push to GitHub")
    st.code(
        'cd "C:\\Users\\iamsh\\OneDrive\\Desktop\\AI Project\\fintel"\n'
        'git add .\n'
        'git commit -m "Dashboard v3 update"\n'
        'git push origin main',
        language="powershell"
    )


# ── MAIN ROUTER ───────────────────────────────────────────────────────────────

def main():
    init_database()

    if st.session_state.get("detail_id"):
        page_company_detail(st.session_state["detail_id"])
        return

    page = st.session_state.get("page", "🏠 Overview")
    if   page == "🏠 Overview":    page_overview()
    elif page == "🔍 IPO Scanner": page_scanner()
    elif page == "📈 Pipeline":    page_pipeline()
    elif page == "💼 Portfolio":   page_portfolio()
    elif page == "🔥 Heatmap":     page_heatmap()
    elif page == "⚙️ System":      page_system()
    else:
        page_overview()


if __name__ == "__main__":
    main()
