"""
AGENT 2: SIGNAL ANALYST (Phase 3)
================================
Tracks post-IPO companies, fetches daily market and sentiment data,
calculates technical indicators, scores them, and generates signals.
"""
import sys, os, time, json
import urllib.parse
from datetime import datetime, timedelta

import yfinance as yf
import pandas as pd
import ta
import feedparser
import requests

from rich.console import Console
from rich.table import Table
from rich.progress import track

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.db import init_database, get_tracked_companies, save_signal_score
from utils.llm import check_ollama_running, ask_llm_for_json
from utils.logger import logger

console = Console()


# ── 1. MARKET DATA ────────────────────────────────────────────────────────────

def fetch_market_data(ticker: str, days: int = 90) -> pd.DataFrame:
    """Fetches daily price history from Yahoo Finance."""
    try:
        t  = yf.Ticker(ticker)
        df = t.history(period=f"{days}d")
        if df.empty:
            logger.warning(f"No price data for {ticker} — may be unlisted/delisted")
            return None
        return df
    except Exception as e:
        logger.warning(f"Failed to fetch market data for {ticker}: {e}")
        return None


def calculate_technicals(df: pd.DataFrame) -> dict:
    """
    Calculates RSI, MACD, SMA20 using ta library and generates a score.
    
    WHY len < 26 CHECK: MACD needs 26 rows minimum for its slow moving
    average. Less than that returns all NaN and crashes the calculation.
    """
    if df is None or len(df) < 26:
        return {
            "technical_score":   50,
            "rsi_14":            None,
            "technical_summary": "Insufficient data (need 26+ days)",
            "price":             None
        }

    try:
        df = df.copy()
        df['RSI_14']     = ta.momentum.RSIIndicator(df['Close'], window=14).rsi()
        macd             = ta.trend.MACD(df['Close'])
        df['MACD']       = macd.macd()
        df['MACD_Signal'] = macd.macd_signal()
        df['SMA_20']     = ta.trend.SMAIndicator(df['Close'], window=20).sma_indicator()

        latest  = df.iloc[-1]
        rsi     = latest['RSI_14']
        price   = latest['Close']
        sma20   = latest['SMA_20']
        score   = 50
        summary = []

        if pd.notna(rsi):
            if rsi < 30:
                score += 20
                summary.append("Oversold RSI<30 — Reversal possible")
            elif rsi > 70:
                score -= 20
                summary.append("Overbought RSI>70 — Pullback likely")
            else:
                summary.append(f"RSI neutral ({round(rsi,1)})")

        if pd.notna(latest['MACD']) and pd.notna(latest['MACD_Signal']):
            if latest['MACD'] > latest['MACD_Signal']:
                score += 15
                summary.append("MACD bullish crossover")
            else:
                score -= 10
                summary.append("MACD bearish")

        if pd.notna(sma20) and pd.notna(price):
            if price > sma20:
                score += 10
                summary.append("Price above SMA20")
            else:
                score -= 10
                summary.append("Price below SMA20")

        return {
            "technical_score":   int(max(0, min(100, score))),
            "rsi_14":            round(float(rsi), 2) if pd.notna(rsi) else None,
            "technical_summary": " | ".join(summary) if summary else "Neutral",
            "price":             round(float(price), 2) if pd.notna(price) else None
        }

    except Exception as e:
        logger.error(f"Technical calculation failed: {e}")
        return {"technical_score": 50, "rsi_14": None, "technical_summary": "Error", "price": None}


# ── 2. SENTIMENT ──────────────────────────────────────────────────────────────

def fetch_recent_news(company_name: str, ticker: str) -> str:
    """
    Fetches news via Google News RSS using requests + feedparser.
    
    WHY requests FIRST: feedparser sends a blocked User-Agent on some
    servers. We fetch raw text with requests (our header), then pass
    text to feedparser for parsing. Same fix as ipo_scout.py.
    Limit to 5 headlines — local 7B models truncate on long prompts.
    """
    query = urllib.parse.quote(f'"{company_name}" stock')
    url   = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

    try:
        headers  = {"User-Agent": "FinTel Research Tool uniquestar333@gmail.com"}
        response = requests.get(url, headers=headers, timeout=10)
        feed     = feedparser.parse(response.text)

        # Top 5 only — prevents LLM truncation on 7B models
        headlines = [entry.title for entry in feed.entries[:5]]

        if not headlines:
            return "No recent news found."

        return "\n".join(f"- {h}" for h in headlines)

    except Exception as e:
        logger.warning(f"News fetch failed for {ticker}: {e}")
        return "Error fetching news."


def analyse_sentiment_with_ai(company_name: str, news_text: str) -> dict:
    """
    Uses Ollama to score sentiment.
    
    BUG FIX: ask_llm_for_json can return a list [] instead of dict {}
    if the LLM wraps its answer in a JSON array. We check type before
    calling .get() to prevent 'list has no attribute get' crash.
    
    PROMPT FIX: Shorter prompt = less truncation from 7B local models.
    """
    neutral = {
        "sentiment_score": 50,
        "news_summary":    "No news data.",
        "key_catalysts":   "None",
        "key_risks":       "None"
    }

    if not news_text or news_text in ("No recent news found.", "Error fetching news."):
        return neutral

    # Short prompt — prevents 7B model truncation
    prompt = f"""Analyse news sentiment for {company_name} as a stock investor.

News:
{news_text}

Return ONLY this JSON (no extra text):
{{"sentiment_score": <0-100>, "news_summary": "<1 sentence>", "key_catalysts": "<10 words max>", "key_risks": "<10 words max>"}}"""

    try:
        response = ask_llm_for_json(prompt)

        # BUG FIX: handle list response from LLM
        if isinstance(response, list):
            response = response[0] if response else {}

        if not isinstance(response, dict) or "sentiment_score" not in response:
            logger.warning(f"Unexpected LLM response type for {company_name}: {type(response)}")
            return neutral

        response['sentiment_score'] = int(response.get('sentiment_score', 50))
        return response

    except Exception as e:
        logger.error(f"AI Sentiment failed for {company_name}: {e}")
        return neutral


# ── 3. MAIN SIGNAL PIPELINE ───────────────────────────────────────────────────

def analyse_company(filing: dict) -> dict:
    """Generate a signal for a single IPO filing record and save it.

    Returns the signal dictionary (same structure as save_signal_score input).
    This can be invoked from the dashboard when the user requests an on‑demand
    analysis of a specific ticker.
    """
    ticker = filing.get('ticker')
    name   = filing.get('company_name')
    fundamental = filing.get('interest_score', 50)

    # 1. Technicals
    df       = fetch_market_data(ticker)
    tech     = calculate_technicals(df)

    # 2. Sentiment
    news      = fetch_recent_news(name, ticker)
    sentiment = analyse_sentiment_with_ai(name, news)

    composite   = int(
        (fundamental                   * 0.40) +
        (tech.get('technical_score', 50) * 0.40) +
        (sentiment.get('sentiment_score', 50) * 0.20)
    )

    signal = {
        "ticker":            ticker,
        "analysis_date":     datetime.now().strftime("%Y-%m-%d"),
        "technical_score":   tech.get('technical_score', 50),
        "sentiment_score":   sentiment.get('sentiment_score', 50),
        "sector_score":      0,
        "fundamental_score": fundamental,
        "composite_score":   composite,
        "news_summary":      sentiment.get('news_summary', ''),
        "technical_summary": tech.get('technical_summary', ''),
        "key_catalysts":     sentiment.get('key_catalysts', ''),
        "key_risks":         sentiment.get('key_risks', ''),
        "price_at_analysis": tech.get('price') or 0.0,
        "rsi_14":            tech.get('rsi_14') or 0.0,
    }
    save_signal_score(signal)
    return signal


def generate_signals():
    console.rule("[bold magenta]📈 FinTel Signal Analyst[/bold magenta]")

    if not check_ollama_running():
        console.print("[bold red]❌ Ollama not running![/bold red]")
        return

    init_database()
    companies = get_tracked_companies()

    if not companies:
        console.print("[yellow]No tracked companies found with tickers and interest_score >= 70.[/yellow]")
        console.print("[dim]Fix: assign tickers in DB or lower the score threshold in get_tracked_companies()[/dim]")
        return

    console.print(f"[dim]Analysing {len(companies)} tracked companies...[/dim]\n")
    results = []

    for comp in track(companies, description="Generating Signals..."):
        ticker = comp['ticker']
        name   = comp['company_name']

        # 1. Technicals
        df       = fetch_market_data(ticker)
        tech     = calculate_technicals(df)

        # 2. Sentiment
        news      = fetch_recent_news(name, ticker)
        sentiment = analyse_sentiment_with_ai(name, news)

        # 3. Composite: 40% fundamental, 40% technical, 20% sentiment
        fundamental = comp.get('interest_score', 50)
        composite   = int(
            (fundamental                   * 0.40) +
            (tech.get('technical_score', 50) * 0.40) +
            (sentiment.get('sentiment_score', 50) * 0.20)
        )

        signal = {
            "ticker":            ticker,
            "analysis_date":     datetime.now().strftime("%Y-%m-%d"),
            "technical_score":   tech.get('technical_score', 50),
            "sentiment_score":   sentiment.get('sentiment_score', 50),
            "sector_score":      0,
            "fundamental_score": fundamental,
            "composite_score":   composite,
            "news_summary":      sentiment.get('news_summary', ''),
            "technical_summary": tech.get('technical_summary', ''),
            "key_catalysts":     sentiment.get('key_catalysts', ''),
            "key_risks":         sentiment.get('key_risks', ''),
            "price_at_analysis": tech.get('price') or 0.0,
            "rsi_14":            tech.get('rsi_14') or 0.0,
        }

        save_signal_score(signal)
        results.append((
            ticker,
            composite,
            tech.get('technical_score', 50),
            sentiment.get('sentiment_score', 50),
            fundamental,
            tech.get('price')
        ))

        time.sleep(0.5)

    # Results table
    table = Table(title=f"📊 End of Day Signals — {datetime.now().strftime('%Y-%m-%d')}")
    table.add_column("Ticker",    style="cyan", no_wrap=True)
    table.add_column("Composite", justify="right", style="bold white")
    table.add_column("Technical", justify="right")
    table.add_column("Sentiment", justify="right")
    table.add_column("Fundamental", justify="right")
    table.add_column("Price",     justify="right", style="green")

    results.sort(key=lambda x: x[1], reverse=True)

    for r in results:
        score = r[1]
        color = "green" if score >= 75 else "yellow" if score >= 60 else "red"
        table.add_row(
            r[0],
            f"[{color}]{score}[/{color}]",
            str(r[2]),
            str(r[3]),
            str(r[4]),
            f"${r[5]}" if r[5] else "[dim]N/A (unlisted)[/dim]"
        )

    console.print("\n")
    console.print(table)
    console.print(f"\n[dim]✅ {len(results)} signals saved to fintel.db[/dim]")


if __name__ == "__main__":
    generate_signals()
