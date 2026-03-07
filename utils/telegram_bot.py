"""
FINTEL TELEGRAM ALERT BOT
==========================
Sends alerts to your Telegram when:
  - New high-conviction signal (FinTel score ≥ 75) is detected
  - Collection script finishes overnight
  - Training completes with results summary
  - A portfolio position drops > 10%
  - A position crosses 183-day tax-free threshold

Setup (one-time, 3 minutes):
  1. Open Telegram → search @BotFather → /newbot → name it "FinTel Alerts"
  2. Copy the token BotFather gives you
  3. Message your new bot once (any text)
  4. Run: python utils/telegram_bot.py --setup
     → This finds your chat_id automatically
  5. Add to .env:
       TELEGRAM_BOT_TOKEN=your_token_here
       TELEGRAM_CHAT_ID=your_chat_id_here
"""

import os, sys, requests, sqlite3, argparse
from datetime import datetime, timedelta
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID  = os.getenv("TELEGRAM_CHAT_ID",  "")


# ── CORE SENDER ───────────────────────────────────────────────────────────────

def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """
    Send a message to your Telegram chat.
    Returns True on success, False on failure.
    Silent fail — never crashes the main app.
    """
    if not TOKEN or not CHAT_ID:
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={
                "chat_id":    CHAT_ID,
                "text":       text,
                "parse_mode": parse_mode,
            },
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


def setup_get_chat_id():
    """
    Helper: prints your chat_id after you've messaged your bot.
    Run once during setup.
    """
    if not TOKEN:
        print("❌ Set TELEGRAM_BOT_TOKEN in .env first")
        return
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{TOKEN}/getUpdates",
            timeout=10
        )
        updates = resp.json().get("result", [])
        if not updates:
            print("❌ No messages found. Send any message to your bot first, then retry.")
            return
        chat_id = updates[-1]["message"]["chat"]["id"]
        print(f"\n✅ Your chat_id: {chat_id}")
        print(f"Add to .env:  TELEGRAM_CHAT_ID={chat_id}\n")
    except Exception as e:
        print(f"Error: {e}")


# ── ALERT TEMPLATES ───────────────────────────────────────────────────────────

def alert_high_conviction(company_name: str, score: float, sector: str,
                           verdict: str, beat_spy_prob: float,
                           expected_return: float, regime: str,
                           filing_date: str):
    """🎯 New high-conviction signal detected."""
    verdict_emoji = {
        "strong_buy": "🟢", "watch": "🟡",
        "neutral": "⚪",    "avoid": "🔴"
    }.get(verdict, "⚪")

    msg = (
        f"🧠 <b>FinTel Signal Alert</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏢 <b>{company_name}</b>\n"
        f"📁 Sector: {sector or '—'}\n"
        f"📅 Filed:  {str(filing_date or '')[:10]}\n\n"
        f"{verdict_emoji} <b>FinTel Score: {score:.0f}/100</b>\n"
        f"📈 Expected Return:  {f'+{expected_return:.1f}%' if expected_return else '—'}\n"
        f"🏆 Beat S&P500 Prob: {f'{beat_spy_prob:.0f}%' if beat_spy_prob else '—'}\n"
        f"🌍 Regime: <code>{regime or '—'}</code>\n\n"
        f"<i>Open FinTel dashboard for full analysis.</i>"
    )
    return send_message(msg)


def alert_collection_complete(total_ipos: int, years_done: int,
                               total_checkpoints: int, event_flags: int):
    """📦 Historical collection finished overnight."""
    msg = (
        f"📦 <b>FinTel — Collection Complete</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"✅ Historical IPO data collected\n\n"
        f"📊 {total_ipos:,} companies\n"
        f"📅 {years_done} years covered\n"
        f"📍 {total_checkpoints:,} price checkpoints\n"
        f"🚩 {event_flags:,} event flags\n\n"
        f"<b>Next step:</b> Run <code>train_models.py</code>"
    )
    return send_message(msg)


def alert_training_complete(regime_results: list[dict]):
    """🤖 Model training finished."""
    n        = len(regime_results)
    good     = [r for r in regime_results
                if r.get("task_c", {}).get("win_rate", 0) >= 0.63]
    best     = max(regime_results,
                   key=lambda r: r.get("task_c", {}).get("win_rate", 0),
                   default=None)

    best_str = ""
    if best:
        wr = best.get("task_c", {}).get("win_rate", 0)
        best_str = (
            f"\n🏆 Best regime: <b>{best['regime']}</b> "
            f"({wr:.0%} win rate)"
        )

    msg = (
        f"🤖 <b>FinTel — Models Trained</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"✅ Per-regime training complete\n\n"
        f"📊 {n} regimes trained\n"
        f"🎯 {len(good)} meet ≥63% win rate threshold"
        f"{best_str}\n\n"
        f"<b>Next step:</b> Run <code>score_new_ipos.py</code>"
    )
    return send_message(msg)


def alert_portfolio_loss(company_name: str, ticker: str,
                          pct_down: float, invested_eur: float):
    """🔴 Portfolio position loss alert."""
    msg = (
        f"🔴 <b>FinTel — Loss Alert</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <b>{company_name}</b> ({ticker})\n"
        f"📉 Down <b>{abs(pct_down):.1f}%</b>\n"
        f"💶 Invested: €{invested_eur:.0f}\n\n"
        f"<i>Review stop-loss on FinTel dashboard.</i>"
    )
    return send_message(msg)


def alert_tax_threshold(company_name: str, ticker: str,
                         days_held: int, days_remaining: int):
    """💶 Tax-free threshold approaching."""
    if days_remaining == 0:
        msg = (
            f"✅ <b>FinTel — Tax-Free!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎉 <b>{company_name}</b> ({ticker})\n"
            f"✅ {days_held} days held — now <b>tax-free in Luxembourg</b>\n"
            f"<i>Gains from this position are now tax-exempt.</i>"
        )
    else:
        msg = (
            f"⏰ <b>FinTel — Tax Clock Alert</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🏢 <b>{company_name}</b> ({ticker})\n"
            f"⏳ <b>{days_remaining} days</b> until tax-free threshold\n"
            f"📅 {days_held}/183 days held\n"
            f"<i>Hold for {days_remaining} more days to avoid CGT.</i>"
        )
    return send_message(msg)


def alert_daily_digest():
    """
    📋 Daily morning summary — top signals, open P&L, upcoming listings.
    Called by scheduler at 07:30 CET every day.
    """
    try:
        from utils.db import get_connection
        conn = sqlite3.connect(os.path.join(ROOT, "fintel.db"))

        # Top signals from last 7 days
        sc_col  = "fintel_score"
        sec_col = "primary_sector"
        try:
            top = conn.execute(f"""
                SELECT company_name, {sc_col}, {sec_col}, verdict
                FROM ipo_filings
                WHERE {sc_col} IS NOT NULL
                  AND filing_date >= date('now', '-7 days')
                ORDER BY {sc_col} DESC LIMIT 5
            """).fetchall()
        except Exception:
            top = []

        # Open positions
        try:
            positions = conn.execute("""
                SELECT company_name, ticker, buy_price, shares
                FROM portfolio
                WHERE closed = 0 OR closed IS NULL
            """).fetchall()
        except Exception:
            positions = []

        # Upcoming listings
        try:
            upcoming = conn.execute("""
                SELECT company_name, expected_listing_date
                FROM ipo_filings
                WHERE expected_listing_date >= date('now')
                  AND expected_listing_date <= date('now', '+14 days')
                ORDER BY expected_listing_date
            """).fetchall()
        except Exception:
            upcoming = []

        conn.close()

        # Build message
        lines = [
            f"☀️ <b>FinTel Morning Digest</b>",
            f"<i>{datetime.now().strftime('%A, %d %b %Y')}</i>",
            "━━━━━━━━━━━━━━━━━━",
        ]

        if top:
            lines.append("\n🎯 <b>Top Signals (Last 7 Days)</b>")
            for name, score, sector, verdict in top:
                emoji = "🟢" if verdict == "strong_buy" else "🟡"
                lines.append(f"{emoji} {name} — <b>{score:.0f}</b> ({sector or '—'})")
        else:
            lines.append("\n📭 No new signals this week")

        if upcoming:
            lines.append("\n📅 <b>Listings This Week</b>")
            for name, date in upcoming:
                lines.append(f"• {name} → {str(date)[:10]}")

        if positions:
            lines.append(f"\n💼 <b>Open Positions: {len(positions)}</b>")

        lines.append("\n<i>Open FinTel for full details.</i>")
        return send_message("\n".join(lines))

    except Exception:
        return False


def check_and_alert_new_signals(lookback_minutes: int = 30):
    """
    Called by scheduler every 30 min during market hours.
    Sends alert for any new high-conviction signals scored recently.
    """
    try:
        conn     = sqlite3.connect(os.path.join(ROOT, "fintel.db"))
        since    = (datetime.now() - timedelta(minutes=lookback_minutes)).isoformat()
        sc_col   = "fintel_score"
        sec_col  = "primary_sector"

        try:
            rows = conn.execute(f"""
                SELECT company_name, {sc_col},
                       COALESCE({sec_col}, 'Unknown') as sector,
                       verdict, beat_spy_prob,
                       expected_return, regime, filing_date
                FROM ipo_filings
                WHERE {sc_col} >= 75
                  AND scored_at >= ?
                ORDER BY {sc_col} DESC
            """, (since,)).fetchall()
        except Exception:
            rows = []

        conn.close()

        sent = 0
        for row in rows:
            name, score, sector, verdict, bsp, er, regime, fdate = row
            alert_high_conviction(
                company_name    = name,
                score           = score or 0,
                sector          = sector,
                verdict         = verdict or "—",
                beat_spy_prob   = bsp,
                expected_return = er,
                regime          = regime,
                filing_date     = fdate,
            )
            sent += 1

        return sent
    except Exception:
        return 0


def alert_test():
    """Send a test message to verify setup is working."""
    return send_message(
        "🧠 <b>FinTel Bot — Test Message</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "✅ Telegram alerts are configured correctly!\n\n"
        f"<i>Connected at {datetime.now().strftime('%H:%M:%S CET')}</i>"
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FinTel Telegram Bot")
    parser.add_argument("--setup", action="store_true", help="Get your chat_id")
    parser.add_argument("--test",  action="store_true", help="Send test message")
    parser.add_argument("--digest",action="store_true", help="Send daily digest now")
    args = parser.parse_args()

    if args.setup:
        setup_get_chat_id()
    elif args.test:
        if alert_test():
            print("✅ Test message sent!")
        else:
            print("❌ Failed. Check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
    elif args.digest:
        alert_daily_digest()
        print("✅ Digest sent")
    else:
        parser.print_help()
