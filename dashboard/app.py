"""
FinTel Executive Dashboard
Run with:  streamlit run dashboard/app.py
Then open: http://localhost:8501
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime
import yfinance as yf
# helper to scrape IPO calendar; not critical if agent module missing
try:
    from agents.ipo_scout import fetch_expected_listing_date, run_scout, refresh_calendar_for_filings
except ImportError:
    fetch_expected_listing_date = None
    run_scout = None
    refresh_calendar_for_filings = None

# bring in signal analyst for full pipeline
try:
    from agents.signal_analyst import generate_signals
except ImportError:
    generate_signals = None

# ── BACKGROUND WORKER & JOB STATUS ───────────────────────────────────────────
# scheduler stored as a cached resource so it's only started once per server
job_status_template = {
    "scout": None,
    "calendar": None,
    "signals": None,
    "portfolio": None,
    "prices": None,
}

@st.cache_resource
def get_job_status():
    # mutable dict that persists across reruns
    return job_status_template.copy()

status = get_job_status()

def mark(job_name: str):
    status[job_name] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    @st.cache_resource
    def get_scheduler():
        sched = BackgroundScheduler()
        # daily IPO scout
        if run_scout:
            def job_scout():
                run_scout(days_back=30, min_score=0)
                mark("scout")
            sched.add_job(job_scout,
                          trigger=IntervalTrigger(hours=24),
                          id="daily_scout", replace_existing=True)
        # daily calendar refresh
        if refresh_calendar_for_filings:
            def job_cal():
                refresh_calendar_for_filings()
                mark("calendar")
            sched.add_job(job_cal,
                          trigger=IntervalTrigger(hours=24),
                          id="daily_calendar", replace_existing=True)
        # nightly signals (for tracked companies)
        if generate_signals:
            def job_signals():
                generate_signals()
                mark("signals")
            sched.add_job(job_signals,
                          trigger=IntervalTrigger(hours=24),
                          id="daily_signals", replace_existing=True)
        # portfolio metrics update (helper defined later)
        try:
            from utils.db import refresh_portfolio_metrics
            def job_portfolio():
                refresh_portfolio_metrics()
                mark("portfolio")
            sched.add_job(job_portfolio,
                          trigger=IntervalTrigger(hours=24),
                          id="daily_portfolio", replace_existing=True)
        except ImportError:
            pass
        # price history cache for tracked/watchlist/portfolio tickers
        try:
            from agents.signal_analyst import fetch_market_data
            from utils.db import get_tracked_companies, get_portfolio
            def job_cache_prices():
                # fetch for tracked companies
                for comp in get_tracked_companies():
                    fetch_market_data(comp.get('ticker'))
                # also cache for open portfolio positions
                for pos in get_portfolio():
                    fetch_market_data(pos.get('ticker'))
                mark("prices")
            sched.add_job(job_cache_prices,
                          trigger=IntervalTrigger(hours=24),
                          id="daily_price_cache", replace_existing=True)
        except ImportError:
            pass

        sched.start()
        return sched

    # start scheduler once
    _ = get_scheduler()
except Exception:
    pass

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
from utils.llm import generate_company_summary
from agents.signal_analyst import analyse_company

# ── PAGE CONFIG ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="FinTel", page_icon="🧠", layout="wide",
                   initial_sidebar_state="expanded")

# ── STYLING ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500&family=JetBrains+Mono:wght@400;500&display=swap');
.stApp { background:#0a0e1a; color:#e2e8f0; font-family:'DM Sans',sans-serif; }
#MainMenu,footer,header { visibility:hidden; }
section[data-testid="stSidebar"] { background:#0d1220; border-right:1px solid #1e2d4a; }
.fintel-title { font-family:'DM Serif Display',serif; font-size:2.2rem; color:#e2e8f0; line-height:1.1; }
.fintel-sub { font-size:0.8rem; color:#4a6080; letter-spacing:0.15em; text-transform:uppercase; }
.kpi-card { background:linear-gradient(135deg,#111827,#0d1525); border:1px solid #1e2d4a; border-radius:12px; padding:20px 24px; }
.kpi-val { font-family:'JetBrains Mono',monospace; font-size:2rem; color:#38bdf8; }
.kpi-lbl { font-size:0.72rem; color:#4a6080; text-transform:uppercase; letter-spacing:0.12em; margin-top:4px; }
.company-row { background:#0d1525; border:1px solid #1e2d4a; border-left:4px solid #0369a1; border-radius:8px; padding:14px 18px; margin-bottom:8px; }
.company-name { font-size:0.95rem; font-weight:600; color:#e2e8f0; }
.company-sector { font-size:0.72rem; color:#38bdf8; text-transform:uppercase; letter-spacing:0.1em; }
.score-hi { display:inline-block; background:#065f46; color:#6ee7b7; font-family:'JetBrains Mono',monospace; font-size:0.8rem; padding:2px 10px; border-radius:20px; }
.score-md { display:inline-block; background:#78350f; color:#fcd34d; font-family:'JetBrains Mono',monospace; font-size:0.8rem; padding:2px 10px; border-radius:20px; }
.score-lo { display:inline-block; background:#450a0a; color:#fca5a5; font-family:'JetBrains Mono',monospace; font-size:0.8rem; padding:2px 10px; border-radius:20px; }
.tax-badge { display:inline-block; background:#0c2a20; color:#34d399; font-size:0.68rem; padding:2px 7px; border-radius:4px; border:1px solid #065f46; margin-left:8px; }
.info-box { background:#0c1a2a; border:1px solid #1e2d4a; border-left:4px solid #38bdf8; border-radius:6px; padding:12px 16px; margin-bottom:12px; font-size:0.84rem; color:#94a3b8; }
</style>
""", unsafe_allow_html=True)

# ── DATA ──────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_filings(days, min_score):
    try:
        init_database()
        return get_recent_filings(days=days, min_score=min_score)
    except Exception:
        return []

@st.cache_data(ttl=300)
def load_sector_chart(days):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("""
            SELECT COALESCE(primary_sector,'unclassified') as sector,
                   COUNT(*) as count, AVG(interest_score) as avg_score
            FROM ipo_filings
            WHERE filing_date >= date('now','-'||?||' days')
            AND primary_sector IS NOT NULL
            GROUP BY primary_sector ORDER BY count DESC
        """, (days,))
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


@st.cache_data(ttl=300)
def load_watchlist(min_score):
    try:
        init_database()
        return get_watchlist(min_score)
    except Exception:
        return []


@st.cache_data(ttl=300)
def load_portfolio():
    try:
        init_database()
        return get_portfolio()
    except Exception:
        return []

@st.cache_data(ttl=300)
def load_upcoming_listings(days):
    try:
        init_database()
        return get_upcoming_listings(days)
    except Exception:
        return []

# ── SIDEBAR ───────────────────────────────────────────────────────────────────

# handle deep-dive navigation using session state (fallback to query params if available)
if 'detail_id' not in st.session_state:
    # check URL only once
    if hasattr(st, 'query_params'):
        qp = st.query_params.to_dict()
        if 'company' in qp:
            try:
                st.session_state.detail_id = int(qp.get('company')[0])
            except Exception:
                st.error("Invalid company id in URL")
                st.stop()
# convenience variable
cid = st.session_state.get('detail_id', None)

if cid is not None:
    # debug log (can remove later)
    st.write(f"navigating to company {cid}")
    def show_company_details(filing_id: int):
        filing = get_filing_by_id(filing_id)
        # if there is no ticker we show listing info and optionally allow a manual calendar lookup
        if not filing.get('ticker'):
            exp = filing.get('expected_listing_date')
            if exp:
                st.markdown(f"<span style='color:#fbbf24;font-size:0.9rem'>Expected listing: {exp[:10]}</span><br/>", unsafe_allow_html=True)
            else:
                # user can trigger a lookup; this avoids hanging the page on load
                if fetch_expected_listing_date:
                    if st.button("🔄 Check calendar for expected listing date", key=f"check_cal_{filing_id}"):
                        with st.spinner("Checking IPO calendars..."):
                            exp = fetch_expected_listing_date(filing.get('company_name',''))
                        if exp:
                            from utils.db import set_expected_listing_date
                            set_expected_listing_date(filing_id, exp)
                            filing['expected_listing_date'] = exp
                            st.success(f"Date found: {exp[:10]}")
                            # rerun to show updated info
                            if hasattr(st, 'rerun'):
                                st.rerun()
                        else:
                            st.info("No date found yet; calendar will keep updating.")
                else:
                    st.markdown("<span style='color:#f87171;font-size:0.9rem'>" \
                                "Listing date not yet available. " \
                                "The system will keep checking external calendars automatically.</span><br/>", unsafe_allow_html=True)

        # helper to fetch historical price data
        def get_price_history(ticker: str, period='1y', interval='1d'):
            try:
                df = yf.download(ticker, period=period, interval=interval, progress=False)
                df.reset_index(inplace=True)
                return df
            except Exception as e:
                st.error(f"Failed to fetch price data: {e}")
                return pd.DataFrame()

        if not filing:
            st.error("Company not found")
            return
        # top back button for easy navigation (UI directive)
        if st.button("⟵ Back", key=f"back_top_{filing_id}"):
            st.session_state.pop('detail_id', None)
            # navigate back to scanner per UI directive
            st.session_state['page'] = "🔍 IPO Scanner"
            if hasattr(st, 'rerun'):
                st.rerun()
        st.markdown(f"<div class='fintel-title'>{filing.get('company_name','')}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='fintel-sub'>{(filing.get('ticker') or '').upper()}</div><br/>", unsafe_allow_html=True)
        st.markdown(f"**Sector:** {filing.get('primary_sector','unknown').replace('_',' ').title()}<br/>"
                    f"**Filed:** {filing.get('filing_date','')[:10]}<br/>"
                    f"**Interest score:** {filing.get('interest_score','?')}<br/>", unsafe_allow_html=True)
        # prepare ticker variable for downstream sections
        ticker = (filing.get('ticker') or '').upper()
        # if no ticker yet display listing date if known, otherwise note that
        if not ticker:
            exp = filing.get('expected_listing_date')
            if exp:
                st.markdown(f"<span style='color:#fbbf24;font-size:0.9rem'>Expected listing: {exp[:10]}</span><br/>", unsafe_allow_html=True)
            else:
                st.markdown("<span style='color:#f87171;font-size:0.9rem'>" \
                            "Listing date not yet available. " \
                            "The system will keep checking external calendars automatically.</span><br/>", unsafe_allow_html=True)
        if filing.get('filing_url'):
            st.markdown(f"[View SEC filing]({filing.get('filing_url')})")
        if filing.get('score_rationale'):
            st.markdown(f"\n**Rationale:** {filing.get('score_rationale')}\n")

        # price chart with technical indicators
        ticker = (filing.get('ticker') or '').upper()
        if ticker:
            hist = get_price_history(ticker, period='1y', interval='1d')
            if not hist.empty:
                # calculate RSI and MACD for overlays
                try:
                    import ta
                    hist['RSI_14'] = ta.momentum.RSIIndicator(hist['Close'], window=14).rsi()
                    macd = ta.trend.MACD(hist['Close'])
                    hist['MACD'] = macd.macd()
                    hist['MACD_Signal'] = macd.macd_signal()
                except Exception:
                    pass

                st.markdown("---\n### Price chart (1 year)")
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=hist['Date'], y=hist['Close'], mode='lines', name='Close'))
                # add RSI on secondary y
                if 'RSI_14' in hist.columns:
                    fig.add_trace(go.Scatter(x=hist['Date'], y=hist['RSI_14'], mode='lines', name='RSI', yaxis='y2', line=dict(dash='dot')))
                # add MACD histogram
                if 'MACD' in hist.columns and 'MACD_Signal' in hist.columns:
                    fig.add_trace(go.Bar(x=hist['Date'], y=hist['MACD'] - hist['MACD_Signal'], name='MACD Hist', yaxis='y3', marker=dict(color='#636efa')))
                    fig.add_trace(go.Scatter(x=hist['Date'], y=hist['MACD'], mode='lines', name='MACD', yaxis='y3', line=dict(color='#636efa')))
                    fig.add_trace(go.Scatter(x=hist['Date'], y=hist['MACD_Signal'], mode='lines', name='MACD Signal', yaxis='y3', line=dict(color='#ef553b')))
                fig.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                    font=dict(color='#94a3b8'), margin=dict(l=0,r=0,t=20,b=20),
                    yaxis=dict(title='Price'),
                    yaxis2=dict(title='RSI', overlaying='y', side='right', range=[0,100], showgrid=False),
                    yaxis3=dict(title='MACD', anchor='free', overlaying='y', side='left', position=0.05, showgrid=False)
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No price history available for this ticker.")
        # AI summary
        if ticker:
            existing_summary = filing.get('ai_summary')
            if existing_summary:
                st.markdown("---\n### AI Summary")
                st.markdown(existing_summary)
            if st.button("🧠 Generate AI summary", key=f"ai_{filing_id}"):
                with st.spinner("Generating summary..."):
                    summary = generate_company_summary(filing)
                    from utils.db import set_ai_summary
                    success = set_ai_summary(filing_id, summary)
                    if success:
                        st.success("Summary saved")
                        if hasattr(st,'rerun'):
                            st.rerun()
                    else:
                        st.error(f"Failed: filing {filing_id} not found in database")

        # run signal analyst button and quick summary
        if ticker:
            # show existing summary if available
            sigs = get_signals_for_ticker(ticker)
            if sigs:
                latest = sigs[0]
                st.markdown("---\n### Latest Signal Summary")
                st.markdown(f"**Composite:** {latest.get('composite_score')}  ")
                if latest.get('technical_summary'):
                    st.markdown(f"- Tech: {latest.get('technical_summary')}")
                if latest.get('news_summary'):
                    st.markdown(f"- News: {latest.get('news_summary')}")
                if latest.get('key_catalysts'):
                    st.markdown(f"- Catalysts: {latest.get('key_catalysts')}")
                if latest.get('key_risks'):
                    st.markdown(f"- Risks: {latest.get('key_risks')}")
            if st.button("🔍 Run signal analyst for this company"):
                with st.spinner("Analysing..."):
                    signal = analyse_company(filing)
                st.success(f"Composite score {signal.get('composite_score')} saved")
                if hasattr(st, 'rerun'):
                    st.rerun()

        # watchlist / portfolio quick actions
        if ticker:
            # watchlist status
            if is_in_watchlist(filing_id):
                st.markdown('<span style="color:#94a3b8;font-size:0.9rem">✔ in watchlist</span>', unsafe_allow_html=True)
            else:
                if st.button("➕ Add to watchlist", key=f"detail_wl_{filing_id}"):
                    res = add_to_watchlist(filing_id, conviction_score=filing.get('interest_score') or 0)
                    if res>0:
                        st.success("Added to watchlist")
                        if hasattr(st,'rerun'):
                            st.rerun()
            # portfolio status
            from utils.db import get_portfolio
            haspos = any(p.get('ticker','').upper() == ticker for p in get_portfolio(False))
            if haspos:
                st.markdown('<span style="color:#94a3b8;font-size:0.9rem">✔ in portfolio</span>', unsafe_allow_html=True)
            else:
                if st.button("➕ Add to portfolio", key=f"detail_pf_{filing_id}"):
                    from utils.db import add_position
                    pid = add_position(ticker, filing.get('company_name',''), datetime.now().strftime("%Y-%m-%d"), 0.0, 0.0)
                    if pid>0:
                        st.success("Position created – fill details on Portfolio page")
                        if hasattr(st,'rerun'):
                            st.rerun()

        # signals
        signals = get_signals_for_ticker(filing.get('ticker',''))
        if signals:
            st.markdown("---\n### Signal history")
            df = pd.DataFrame(signals)
            st.dataframe(df[['analysis_date','composite_score','technical_score','sentiment_score']])

        # portfolio entry form
        if ticker:
            st.markdown("---\n### Portfolio")
            col1, col2, col3, col4 = st.columns(4)
            entry_date = col1.date_input("Entry date", datetime.now().date())
            price = col2.number_input("Entry price", min_value=0.0, format="%.2f")
            shares = col3.number_input("Shares", min_value=0.0, format="%.2f")
            if col4.button("➕ Add position"):
                from utils.db import add_position
                pid = add_position(ticker, filing.get('company_name',''), entry_date.strftime("%Y-%m-%d"), price, shares)
                if pid > 0:
                    st.success("Position added to portfolio")
                    if hasattr(st, 'rerun'):
                        st.rerun()
                else:
                    st.error("Failed to add position")

            # list open positions for this ticker
            pts = load_portfolio()
            pts = [p for p in pts if p.get('ticker','').upper() == ticker]
            if pts:
                st.markdown(f"<br/><strong>{len(pts)} open position(s) for {ticker}</strong>", unsafe_allow_html=True)
                for p in pts:
                    colA, colB, colC = st.columns([2,1,1])
                    colA.markdown(f"- {p.get('entry_date')} {p.get('shares')} shares @ €{p.get('entry_price')}")
                    exit_price = colB.number_input("Exit price", min_value=0.0, format="%.2f", key=f"exit_{p.get('id')}")
                    if colC.button("Close", key=f"close_{p.get('id')}"):
                        from utils.db import close_position
                        success = close_position(p.get('id'), datetime.now().strftime("%Y-%m-%d"), exit_price)
                        if success:
                            st.success("Position closed")
                            if hasattr(st, 'rerun'):
                                st.rerun()
                        else:
                            st.error("Failed to close position")

        if st.button("⟵ Back", key=f"back_bottom_{filing_id}"):
            st.session_state.pop('detail_id', None)
            # ensure scanner page selected
            st.session_state['page'] = "🔍 IPO Scanner"
            if hasattr(st, 'rerun'):
                st.rerun()

    show_company_details(cid)
    st.stop()

with st.sidebar:
    st.markdown('<div class="fintel-title">🧠 FinTel</div><div class="fintel-sub">Intelligence Platform</div>', unsafe_allow_html=True)
    st.markdown("---")
    # store page choice in session state so we can programmatically navigate later
    page = st.radio("", ["📊 Dashboard","� Pipeline","�🔍 IPO Scanner","📋 Watchlist","💼 Portfolio","⚙️ System"], key="page", label_visibility="collapsed")
    st.markdown("---")
    st.markdown('<div style="font-size:0.68rem;color:#4a6080;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:6px">FILTERS</div>', unsafe_allow_html=True)
    days_back = st.slider("Days back", 7, 90, 30)
    min_score = st.slider("Min score", 0, 100, 60)
    st.markdown("---")
    st.markdown('<div style="font-size:0.68rem;color:#4a6080;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:6px">SYSTEM</div>', unsafe_allow_html=True)
    try:
        import ollama as oc
        oc.Client(host="http://localhost:11434").list()
        st.markdown("🟢 <span style='font-size:0.8rem;color:#34d399'>Ollama: Online</span>", unsafe_allow_html=True)
    except Exception:
        st.markdown("🔴 <span style='font-size:0.8rem;color:#f87171'>Ollama: Offline</span>", unsafe_allow_html=True)
    st.markdown(f"<span style='font-size:0.72rem;color:#4a6080'>Updated: {datetime.now().strftime('%H:%M:%S')}</span>", unsafe_allow_html=True)
    if st.button("🔄 Refresh", use_container_width=True):
        st.cache_data.clear(); st.rerun()
    if st.button("🗓 Backfill calendar", use_container_width=True):
        with st.spinner("Updating calendar cache…"):
            from agents.ipo_scout import refresh_calendar_for_filings
            n = refresh_calendar_for_filings()
        st.success(f"Calendar updated for {n} companies")

# ── DASHBOARD PAGE ────────────────────────────────────────────────────────────
if page == "📊 Dashboard":
    st.markdown('<div class="fintel-title">Market Intelligence</div><div class="fintel-sub">IPO Research · Signal Analysis · Portfolio</div><br/>', unsafe_allow_html=True)

    filings     = load_filings(days_back, 0)
    sector_data = load_sector_chart(days_back)
    high_score  = [f for f in filings if (f.get("interest_score") or 0) >= 75]
    tracked     = [f for f in filings if f.get("primary_sector") not in [None,"other"]]
    upcoming    = load_upcoming_listings(days_back)
    wl = load_watchlist(min_score)
    pts = load_portfolio()

    c1,c2,c3,c4,c5 = st.columns([1,1,1,1,1])
    for col, val, lbl in [
        (c1, len(filings),     "Filings Tracked"),
        (c2, len(high_score),  "High Conviction 75+"),
        (c3, len(tracked),     "In Target Sectors"),
        (c4, len(pts),         "Open Positions"),
        (c5, len(upcoming),    "Upcoming Listings"),
    ]:
        col.markdown(f'<div class="kpi-card"><div class="kpi-val">{val}</div><div class="kpi-lbl">{lbl}</div></div>', unsafe_allow_html=True)

    st.markdown("<br/>", unsafe_allow_html=True)
    
    # portfolio performance snapshot
    st.markdown("---\n### Portfolio Performance")
    closed_trades = get_closed_positions()
    if closed_trades:
        total_realized_pnl = sum(t.get('realised_pnl_eur', 0) for t in closed_trades)
        total_return_pct = sum(t.get('realised_pnl_pct', 0) for t in closed_trades) / len(closed_trades) if closed_trades else 0
        winners = len([t for t in closed_trades if (t.get('realised_pnl_eur', 0) or 0) > 0])
        win_rate = winners / len(closed_trades) * 100 if closed_trades else 0
        
        pcol1, pcol2, pcol3, pcol4 = st.columns(4)
        pcol1.metric("Closed Trades", len(closed_trades), delta=None)
        pcol2.metric("Win Rate", f"{win_rate:.1f}%", delta=None)
        pcol3.metric("Avg. Return", f"{total_return_pct:.2f}%", delta=None)
        pcol4.metric("Total P/L (€)", f"€{total_realized_pnl:.0f}", delta=None)
    else:
        st.markdown('<div class="info-box">No closed trades yet. Start by adding positions to your portfolio.</div>', unsafe_allow_html=True)

    st.markdown("<br/>", unsafe_allow_html=True)
    left, right = st.columns([1.2,1])

    # score trend over time
    if filings:
        df_scores = pd.DataFrame(filings)
        df_scores['filing_date'] = pd.to_datetime(df_scores['filing_date'])
        df_scores = df_scores.dropna(subset=['interest_score'])
        if not df_scores.empty:
            trend = df_scores.groupby(df_scores['filing_date'].dt.date)['interest_score'].mean().reset_index()
            fig_trend = go.Figure(go.Scatter(x=trend['filing_date'], y=trend['interest_score'], mode='lines+markers', line=dict(color='#38bdf8')))
            fig_trend.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color='#94a3b8'), margin=dict(l=0,r=0,t=10,b=10), height=200,
                xaxis=dict(showgrid=True,gridcolor='#1e2d4a',color='#4a6080',title='Date'),
                yaxis=dict(showgrid=True,gridcolor='#1e2d4a',color='#4a6080',title='Avg Score'))
            st.plotly_chart(fig_trend, use_container_width=True)

    # sector heatmap
    if filings:
        heat = pd.DataFrame(filings)
        heat = heat[heat.get('primary_sector').notnull()]
        heat['score_bin'] = pd.cut(heat['interest_score'], bins=[0,60,75,100], labels=['Low','Mid','High'])
        pivot = heat.pivot_table(index='primary_sector', columns='score_bin', values='id', aggfunc='count').fillna(0)
        if not pivot.empty:
            fig_heat = go.Figure(data=go.Heatmap(
                z=pivot.values,
                x=pivot.columns,
                y=[s.replace('_',' ').title() for s in pivot.index],
                colorscale='Viridis'))
            fig_heat.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                                   font=dict(color='#94a3b8'), margin=dict(l=0,r=0,t=20,b=20), height=300)
            st.plotly_chart(fig_heat, use_container_width=True)


    with left:
        st.markdown("#### Sector Distribution")
        if sector_data:
            df = pd.DataFrame(sector_data)
            df["label"] = df["sector"].str.replace("_"," ").str.title()
            fig = go.Figure(go.Bar(
                x=df["count"], y=df["label"], orientation="h",
                marker=dict(color=df["avg_score"], colorscale=[[0,"#1e3a5f"],[1,"#38bdf8"]], showscale=True),
                text=df["count"], textposition="outside", textfont=dict(color="#94a3b8",size=11)
            ))
            fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#94a3b8",family="DM Sans"), margin=dict(l=0,r=40,t=10,b=10), height=300,
                xaxis=dict(showgrid=True,gridcolor="#1e2d4a",color="#4a6080"),
                yaxis=dict(color="#94a3b8"))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.markdown('<div class="info-box">No sector data yet. Run the IPO Scout first:<br/><code>python agents/ipo_scout.py</code></div>', unsafe_allow_html=True)

    with right:
        st.markdown("#### Score Distribution")
        if filings:
            scores = [f.get("interest_score") for f in filings if f.get("interest_score") is not None]
            fig2 = go.Figure(go.Histogram(x=scores, nbinsx=20,
                marker=dict(color="#1d6b9e", line=dict(color="#38bdf8",width=1))))
            fig2.add_vline(x=min_score, line_dash="dash", line_color="#f59e0b",
                annotation_text=f"Min: {min_score}", annotation_font_color="#f59e0b", annotation_font_size=10)
            fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#94a3b8"), margin=dict(l=0,r=10,t=10,b=10), height=300,
                xaxis=dict(showgrid=True,gridcolor="#1e2d4a",color="#4a6080",title="Score"),
                yaxis=dict(showgrid=True,gridcolor="#1e2d4a",color="#4a6080",title="Count"))
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.markdown('<div class="info-box">Run IPO Scout to populate charts.</div>', unsafe_allow_html=True)

    st.markdown('<div class="info-box">🇱🇺 <strong>Luxembourg Tax:</strong> Holdings &gt; 183 days = zero capital gains tax for Luxembourg individual investors. Every FinTel recommendation includes the tax-free date.</div>', unsafe_allow_html=True)

# ── IPO PIPELINE PAGE ────────────────────────────────────────────────────────
elif page == "📈 Pipeline":
    st.markdown('<div class="fintel-title">IPO Pipeline</div><div class="fintel-sub">New → Tracked → Positions → Closed</div><br/>', unsafe_allow_html=True)
    filings = load_filings(days_back, 0)
    wl = load_watchlist(0)
    wl_ids = {e['filing_id'] for e in wl}
    pts = load_portfolio()
    closed = get_closed_positions()

    new_filings = [f for f in filings if f.get('id') not in wl_ids]

    tab_new, tab_tracked, tab_pos, tab_closed = st.tabs(["New","Tracked","Positions","Closed"])

    with tab_new:
        st.markdown("#### Newly discovered filings")
        if not new_filings:
            st.markdown('<div class="info-box">No new filings based on your filters.</div>', unsafe_allow_html=True)
        else:
            for f in new_filings:
                score = f.get("interest_score") or 0
                badge = f'<span class="score-hi">{score}</span>' if score >= 75 else f'<span class="score-md">{score}</span>' if score >= 60 else f'<span class="score-lo">{score}</span>'
                sector = (f.get("primary_sector") or "unknown").replace("_"," ").title()
                st.markdown(f"""
                <div class="company-row">
                  <div style="display:flex;justify-content:space-between;align-items:flex-start">
                    <div>
                      <span class="company-name">{f.get('company_name','?')}</span>
                      <span class="tax-badge">🇱🇺 Hold 183d → tax-free</span><br/>
                      <span class="company-sector">{sector}</span>
                      <span style="color:#4a6080;font-size:0.72rem"> · Filed: {(f.get('filing_date') or '')[:10]}</span>
                    </div>
                    <div>{badge}</div>
                  </div>
                  <div style="font-size:0.8rem;color:#64748b;margin-top:6px">{f.get('score_rationale') or 'Run signal analyst for full analysis.'}</div>
                </div>""", unsafe_allow_html=True)
                if st.button(f"View details: {f.get('company_name','?')}", key=f"nav_new_{f.get('id')}"):
                    st.session_state.detail_id = f.get('id')
                    if hasattr(st, 'rerun'):
                        st.rerun()
                if f.get('id') not in wl_ids and f.get('ticker'):
                    if st.button("➕ Add to watchlist", key=f"addpw_{f.get('id')}"):
                        result = add_to_watchlist(f.get('id'), conviction_score=score)
                        if result > 0:
                            st.success("Added to watchlist")
                            st.cache_data.clear()
                            if hasattr(st, 'rerun'):
                                st.rerun()
                        else:
                            st.error("Unable to add – ticker not available yet. Try again after the company lists.")
    with tab_tracked:
        st.markdown("#### Watchlist")
        if not wl:
            st.markdown('<div class="info-box">Watchlist is empty.</div>', unsafe_allow_html=True)
        else:
            for entry in wl:
                score = entry.get("conviction_score") or 0
                badge = (
                    f'<span class="score-hi">{score}</span>' if score >= 75
                    else f'<span class="score-md">{score}</span>' if score >= 60
                    else f'<span class="score-lo">{score}</span>'
                )
                st.markdown(f"""
                <div class="company-row">
                  <div style="display:flex;justify-content:space-between;align-items:flex-start">
                    <div>
                      <span class="company-name">{entry.get('company_name','?')}</span>
                      <span class="company-sector">{(entry.get('ticker') or '').upper()}</span><br/>
                      <span style="color:#4a6080;font-size:0.72rem">added: {(entry.get('created_at') or '')[:10]}</span>
                    </div>
                    <div>{badge}</div>
                  </div>
                  <div style="margin-top:6px;font-size:0.8rem;color:#64748b">{entry.get('entry_rationale') or ''}</div>
                </div>""", unsafe_allow_html=True)
                if st.button(f"View details: {entry.get('company_name','?')}", key=f"nav_wl2_{entry.get('id')}"):
                    st.session_state.detail_id = entry.get('filing_id')
                    if hasattr(st, 'rerun'):
                        st.rerun()
                remove_key = f"rm2_{entry.get('id')}"
                if st.button("Remove", key=remove_key, help="Remove from watchlist"):
                    remove_from_watchlist(entry.get('id'))
                    st.success("Removed")
                    st.cache_data.clear();
                    if hasattr(st,'rerun'):
                        st.rerun()
                # allow moving to portfolio if ticker present
                if entry.get('ticker'):
                    if st.button("➕ Add to portfolio", key=f"push2_{entry.get('id')}"):
                        from utils.db import add_position
                        pid = add_position(entry.get('ticker'), entry.get('company_name'), datetime.now().strftime("%Y-%m-%d"), 0.0, 0.0)
                        if pid>0:
                            st.success("Position created (enter details on Portfolio page)")
    with tab_pos:
        st.markdown("#### Open Positions")
        if not pts:
            st.markdown('<div class="info-box">No open positions.</div>', unsafe_allow_html=True)
        else:
            for p in pts:
                days = p.get('hold_days') or 0
                tax_badge = ''
                warn = ''
                if p.get('tax_free_date'):
                    due = (datetime.strptime(p.get('tax_free_date'), "%Y-%m-%d") - datetime.now()).days
                    tax_badge = f'<span class="tax-badge">🇱🇺 Tax free {p.get("tax_free_date")[:10]} ({due}d)</span>'
                    if due <= 7:
                        warn = '<span style="color:#fbbf24">⚠️ 7d until tax-free</span>'
                pnl = p.get('unrealised_pnl_pct',0)
                pnl_color = "green" if pnl >= 0 else "red"
                if pnl < -10:
                    warn += ' <span style="color:#f87171">⚠️ loss &gt;10%</span>'
                st.markdown(f"""
                <div class="company-row">
                  <div style="display:flex;justify-content:space-between;align-items:center">
                    <div>
                      <span class="company-name">{p.get('ticker')}</span>
                      <span style="color:#4a6080;font-size:0.72rem">entry {p.get('entry_date')[:10]}</span>
                      {tax_badge}
                    </div>
                    <div class="kpi-val" style="color:{pnl_color}">{p.get('unrealised_pnl_pct',0):.1f}%</div>
                  </div>
                  <div style="font-size:0.8rem;color:#64748b">
                    €{p.get('total_invested_eur',0):.2f} · {p.get('shares',0):.2f} shares · {days} days held
                    {warn}
                  </div>
                </div>""", unsafe_allow_html=True)
                if st.button(f"View details: {p.get('ticker')}", key=f"nav_pos_{p.get('id')}"):
                    st.session_state.detail_id = None
                    # could route to company by ticker search later
    with tab_closed:
        st.markdown("#### Closed Positions")
        if not closed:
            st.markdown('<div class="info-box">No closed trades yet.</div>', unsafe_allow_html=True)
        else:
            for p in closed:
                pct = p.get('realised_pnl_pct',0)
                eur = p.get('realised_pnl_eur',0)
                color = "green" if pct>=0 else "red"
                st.markdown(f"- {p.get('ticker')} {p.get('shares')} shares closed {p.get('exit_date')}  — "
                            f"<span style='color:{color}'>{pct:.1f}% (€{eur:.2f})</span>")

# ── IPO SCANNER PAGE ──────────────────────────────────────────────────────────
elif page == "🔍 IPO Scanner":
    st.markdown('<div class="fintel-title">IPO Scanner</div><div class="fintel-sub">SEC EDGAR · Real-Time · AI Classification</div><br/>', unsafe_allow_html=True)

    col_btn, col_txt = st.columns([1,3])
    with col_btn:
        if st.button("▶ Run Scout Now", use_container_width=True, type="primary"):
            with st.spinner("Scanning SEC EDGAR... (5-15 minutes)"):
                try:
                    from agents.ipo_scout import run_scout
                    results = run_scout(days_back=days_back, min_score=min_score)
                    st.success(f"✅ Done — {len(results)} filings processed")
                    st.cache_data.clear(); st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
    with col_txt:
        st.markdown(f'<div style="padding:8px 0;font-size:0.84rem;color:#64748b">Searches SEC EDGAR for S-1/F-1 filings (IPO registrations) from the last {days_back} days. Each company is classified by sector and scored 0–100 by your local AI.</div>', unsafe_allow_html=True)

    st.markdown("---")
    filings = load_filings(days_back, min_score)
    # compute existing watchlist ids to disable duplicates
    existing_wl = {w['filing_id'] for w in load_watchlist(0)}

    if not filings:
        st.markdown('<div class="info-box">No results yet. Click "Run Scout Now" above, or lower your minimum score filter.</div>', unsafe_allow_html=True)
    else:
        st.markdown(f"**{len(filings)} companies** match your filters")
        for f in filings:
            score = f.get("interest_score") or 0
            badge = f'<span class="score-hi">{score}</span>' if score >= 75 else f'<span class="score-md">{score}</span>' if score >= 60 else f'<span class="score-lo">{score}</span>'
            sector = (f.get("primary_sector") or "unknown").replace("_"," ").title()
            # company row html but replace name with placeholder div for button
            st.markdown(f"""
            <div class="company-row">
              <div style="display:flex;justify-content:space-between;align-items:flex-start">
                <div>
                  <span class="company-name">{f.get('company_name','?')}</span>
                  <span class="tax-badge">🇱🇺 Hold 183d → tax-free</span><br/>
                  <span class="company-sector">{sector}</span>
                  <span style="color:#4a6080;font-size:0.72rem"> · Filed: {(f.get('filing_date') or '')[:10]}</span>
                </div>
                <div>{badge}</div>
              </div>
              <div style="font-size:0.8rem;color:#64748b;margin-top:6px">{f.get('score_rationale') or 'Run signal analyst for full analysis.'}</div>
            </div>""", unsafe_allow_html=True)
            # navigation button below to avoid interfering with markup
            if st.button(f"View details: {f.get('company_name','?')}", key=f"nav_{f.get('id')}"):
                st.session_state.detail_id = f.get('id')
                if hasattr(st, 'rerun'):
                    st.rerun()
            key = f"watch_{f.get('id')}"
            ticker = f.get('ticker') or ''
            if ticker:
                if f.get('id') in existing_wl:
                    st.markdown('<span style="color:#94a3b8;font-size:0.72rem">✔ already in watchlist</span>', unsafe_allow_html=True)
                else:
                    if st.button("➕ Add to watchlist", key=key, help="Save this filing to your watchlist"):
                        result = add_to_watchlist(f.get('id'), conviction_score=score)
                        if result > 0:
                            st.success("Added to watchlist")
                            st.cache_data.clear()
                            if hasattr(st, "rerun"):
                                st.rerun()
                            else:
                                st.info("Please refresh the page to see the updated watchlist.")
                        else:
                            st.error("Unable to add – ticker not available yet. Try again after the company lists.")
            else:
                exp = f.get('expected_listing_date')
                if exp:
                    st.markdown(f'<span style="color:#fbbf24;font-size:0.72rem">Ticker unknown – expected listing {exp[:10]}</span>', unsafe_allow_html=True)
                else:
                    st.markdown('<span style="color:#f87171;font-size:0.72rem">Ticker unknown – wait until listing to add.</span>', unsafe_allow_html=True)

# ── WATCHLIST PAGE ────────────────────────────────────────────────────────────
elif page == "📋 Watchlist":
    st.markdown('<div class="fintel-title">Watchlist</div><div class="fintel-sub">High-Conviction Opportunities</div><br/>', unsafe_allow_html=True)
    st.markdown('<div class="info-box">Your watchlist populates automatically as you add high-scoring companies. Use the buttons below to manage it.</div>', unsafe_allow_html=True)
    wl = load_watchlist(min_score)
    if not wl:
        st.markdown('<div class="info-box">No entries yet. Add companies from the IPO Scanner.</div>', unsafe_allow_html=True)
    else:
        st.markdown(f"**{len(wl)} companies on your watchlist**")
        for entry in wl:
            score = entry.get("conviction_score") or 0
            badge = (
                f'<span class="score-hi">{score}</span>' if score >= 75
                else f'<span class="score-md">{score}</span>' if score >= 60
                else f'<span class="score-lo">{score}</span>'
            )
            st.markdown(f"""
            <div class="company-row">
              <div style="display:flex;justify-content:space-between;align-items:flex-start">
                <div>
                  <span class="company-name">{entry.get('company_name','?')}</span>
                  <span class="company-sector">{(entry.get('ticker') or '').upper()}</span><br/>
                  <span style="color:#4a6080;font-size:0.72rem">added: {(entry.get('created_at') or '')[:10]}</span>
                </div>
                <div>{badge}</div>
              </div>
              <div style="margin-top:6px;font-size:0.8rem;color:#64748b">{entry.get('entry_rationale') or ''}</div>
            </div>""", unsafe_allow_html=True)
            if st.button(f"View details: {entry.get('company_name','?')}", key=f"nav_wl_{entry.get('id')}"):
                st.session_state.detail_id = entry.get('filing_id')
                if hasattr(st, 'rerun'):
                    st.rerun()
            remove_key = f"rm_{entry.get('id')}"
            if st.button("Remove", key=remove_key, help="Remove from watchlist"):
                remove_from_watchlist(entry.get('id'))
                st.cache_data.clear()
                if hasattr(st, "rerun"):
                    st.rerun()
                else:
                    st.info("Please refresh the page to see the updated watchlist.")

# ── PORTFOLIO PAGE ────────────────────────────────────────────────────────────
elif page == "💼 Portfolio":
    st.markdown('<div class="fintel-title">Portfolio</div><div class="fintel-sub">Position Tracking · P&L · Tax Status</div><br/>', unsafe_allow_html=True)
    pts = load_portfolio()
    if not pts:
        st.markdown('<div class="info-box">No open positions. Paper trading only.</div>', unsafe_allow_html=True)
    else:
        st.markdown(f"**{len(pts)} open positions**")
        for p in pts:
            days = p.get('hold_days') or 0
            tax_badge = ''
            if p.get('tax_free_date'):
                tax_badge = f'<span class="tax-badge">🇱🇺 Tax free {p.get("tax_free_date")[:10]}</span>'
            st.markdown(f"""
            <div class="company-row">
              <div style="display:flex;justify-content:space-between;align-items:center">
                <div>
                  <span class="company-name">{p.get('ticker')}</span>
                  <span style="color:#4a6080;font-size:0.72rem">entry {p.get('entry_date')[:10]}</span>
                  {tax_badge}
                </div>
                <div class="kpi-val">{p.get('unrealised_pnl_pct',0):.1f}%</div>
              </div>
              <div style="font-size:0.8rem;color:#64748b">
                €{p.get('total_invested_eur',0):.2f} · {p.get('shares',0):.2f} shares · {days} days held
              </div>
            </div>""", unsafe_allow_html=True)

# ── SYSTEM PAGE ─────────────────────────────────────────────────────────────
elif page == "⚙️ System":
    st.markdown('<div class="fintel-title">System Status</div><div class="fintel-sub">Background Jobs & Agents</div><br/>', unsafe_allow_html=True)
    st.markdown("#### Job run times")
    st.write(status)
    st.markdown("---")
    # manual triggers
    if st.button("Run IPO Scout now", use_container_width=True):
        with st.spinner("Scanning SEC EDGAR..."):
            if run_scout:
                run_scout(days_back=30, min_score=0)
                mark("scout")
                st.success("Scout completed")
            else:
                st.error("IPO scout unavailable")
    if st.button("Refresh calendar now", use_container_width=True):
        with st.spinner("Updating calendar cache..."):
            if refresh_calendar_for_filings:
                refresh_calendar_for_filings()
                mark("calendar")
                st.success("Calendar refreshed")
            else:
                st.error("Calendar helper unavailable")
    if st.button("Generate signals now", use_container_width=True):
        with st.spinner("Running signal analyst..."):
            if generate_signals:
                generate_signals()
                mark("signals")
                st.success("Signals generated")
            else:
                st.error("Signal analyst unavailable")
    if st.button("Refresh portfolio metrics", use_container_width=True):
        from utils.db import refresh_portfolio_metrics
        with st.spinner("Updating portfolio..."):
            refresh_portfolio_metrics()
            mark("portfolio")
            st.success("Portfolio refreshed")
    if st.button("Cache market prices now", use_container_width=True):
        from agents.signal_analyst import fetch_market_data
        from utils.db import get_tracked_companies, get_portfolio
        with st.spinner("Fetching price history..."):
            for comp in get_tracked_companies():
                fetch_market_data(comp.get('ticker'))
            for pos in get_portfolio():
                fetch_market_data(pos.get('ticker'))
            mark("prices")
            st.success("Prices cached")

    # signal accuracy
    if st.button("❓ Compute 30d signal accuracy", use_container_width=True):
        with st.spinner("Calculating signal performance..."):
            from utils.db import get_all_signals
            import yfinance as yf
            from datetime import datetime, timedelta
            sigs = get_all_signals()
            total = 0
            wins = 0
            returns = []
            for s in sigs:
                ad = s.get('analysis_date')
                if not ad:
                    continue
                ad_dt = datetime.strptime(ad, "%Y-%m-%d")
                if ad_dt > datetime.now() - timedelta(days=40):
                    continue
                total += 1
                ticker = s.get('ticker')
                price0 = s.get('price_at_analysis')
                try:
                    hist = yf.download(ticker, start=(ad_dt + timedelta(days=30)).strftime("%Y-%m-%d"), end=(ad_dt + timedelta(days=31)).strftime("%Y-%m-%d"), progress=False)
                    if not hist.empty and price0:
                        price1 = hist['Close'].iloc[0]
                        ret = (price1 - price0) / price0 * 100
                        returns.append(ret)
                        if ret > 0:
                            wins += 1
                except Exception:
                    continue
            avg_ret = sum(returns)/len(returns) if returns else 0
            hit_rate = wins/total*100 if total else 0
        st.markdown(f"**Signals evaluated:** {total}")
        st.markdown(f"**Hit rate (positive 30d):** {hit_rate:.1f}%")
        st.markdown(f"**Average 30d return:** {avg_ret:.2f}%")
