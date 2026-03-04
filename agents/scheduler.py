"""
AGENT 3: SCHEDULER (Phase 3)
==========================
Automates the daily execution of FinTel's agents.
Runs IPO Scout (Incremental) and Signal Analyst automatically.
"""

import sys, os
from datetime import datetime
# we may not need APScheduler if running once
from rich.console import Console

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# defer importing heavy modules until needed
from utils.logger import logger

# helper to import IPO scout/analyst at runtime (avoids startup delay)
def _import_agents():
    global run_scout, refresh_calendar_for_filings, generate_signals, refresh_portfolio_metrics, fetch_market_data, get_tracked_companies, get_portfolio
    from agents.ipo_scout import run_scout, refresh_calendar_for_filings
    from agents.signal_analyst import generate_signals, fetch_market_data
    # portfolio helper and company lists
    from utils.db import refresh_portfolio_metrics, get_tracked_companies, get_portfolio



console = Console()

def daily_ipo_scan():
    """Runs the incremental IPO Scout scan."""
    logger.info("⏰ Starting scheduled daily IPO scan (Incremental)...")
    try:
        # Run incremental mode, threshold 50
        run_scout(mode="incremental", min_score=50)
        logger.success("✅ Scheduled IPO scan completed.")
    except Exception as e:
        logger.error(f"Scheduled IPO scan failed: {e}")

def daily_signal_analysis():
    """Runs the Signal Analyst post-market."""
    logger.info("⏰ Starting scheduled daily Signal Analysis...")
    try:
        generate_signals()
        logger.success("✅ Scheduled Signal Analysis completed.")
    except Exception as e:
        logger.error(f"Scheduled Signal Analysis failed: {e}")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run FinTel agents scheduler or execute once.")
    parser.add_argument("--once", action="store_true",
                        help="Run all jobs immediately and exit instead of scheduling.")
    args = parser.parse_args()

    console.rule("[bold cyan]🕰️ FinTel Agent Scheduler[/bold cyan]")
    console.print("[dim]Leave this window running to automate your daily pipelines.[/dim]\n")

    _import_agents()  # load the heavy functions lazily

    # job definitions now that imports are available
    def daily_calendar_refresh():
        logger.info("⏰ Refreshing IPO calendar cache…")
        try:
            n = refresh_calendar_for_filings()
            logger.success(f"✅ Calendar updated for {n} companies.")
        except Exception as e:
            logger.error(f"Calendar refresh failed: {e}")

    def daily_ipo_scan():
        logger.info("⏰ Starting scheduled daily IPO scan (Incremental)...")
        try:
            run_scout(mode="incremental", min_score=50)
            logger.success("✅ Scheduled IPO scan completed.")
        except Exception as e:
            logger.error(f"Scheduled IPO scan failed: {e}")

    def daily_signal_analysis():
        logger.info("⏰ Starting scheduled daily Signal Analysis...")
        try:
            generate_signals()
            logger.success("✅ Scheduled Signal Analysis completed.")
        except Exception as e:
            logger.error(f"Scheduled Signal Analysis failed: {e}")

    def daily_portfolio_update():
        logger.info("⏰ Refreshing portfolio metrics…")
        try:
            refresh_portfolio_metrics()
            logger.success("✅ Portfolio metrics updated.")
        except Exception as e:
            logger.error(f"Portfolio update failed: {e}")

    def daily_price_cache():
        logger.info("⏰ Caching market prices for tracked tickers…")
        try:
            for comp in get_tracked_companies():
                fetch_market_data(comp.get('ticker'))
            for pos in get_portfolio():
                fetch_market_data(pos.get('ticker'))
            logger.success("✅ Price cache refreshed.")
        except Exception as e:
            logger.error(f"Price cache job failed: {e}")

    def daily_ai_summaries():
        """Auto-generate AI summaries for tracked companies that don't have one."""
        logger.info("⏰ Generating AI summaries for tracked companies…")
        try:
            from utils.db import get_ai_summary, set_ai_summary
            from utils.llm import generate_company_summary
            
            companies = get_tracked_companies()
            generated = 0
            for comp in companies:
                filing_id = comp['id']
                if not get_ai_summary(filing_id):
                    summary = generate_company_summary(comp)
                    success = set_ai_summary(filing_id, summary)
                    if success:
                        generated += 1
                    else:
                        logger.warning(f"Failed to save summary for filing {filing_id}")
            logger.success(f"✅ Generated {generated} AI summaries.")
        except Exception as e:
            logger.error(f"AI summary generation failed: {e}")

    if args.once:
        console.print("[yellow]Running all jobs once...[/yellow]")
        daily_calendar_refresh()
        daily_ipo_scan()
        daily_signal_analysis()
        daily_ai_summaries()
        daily_portfolio_update()
        daily_price_cache()
        console.print("[green]All jobs executed; exiting.[/green]")
    else:
        from apscheduler.schedulers.blocking import BlockingScheduler
        scheduler = BlockingScheduler()

        scheduler.add_job(daily_calendar_refresh, 'cron', hour=15, minute=0, timezone='Europe/Luxembourg')
        console.print("[green]► IPO Calendar[/green]        scheduled for [bold]15:00 CE(S)T[/bold] daily")

        scheduler.add_job(daily_ipo_scan, 'cron', hour=18, minute=0, timezone='Europe/Luxembourg')
        console.print("[green]► IPO Scout[/green]            scheduled for [bold]18:00 CE(S)T[/bold] daily")

        scheduler.add_job(daily_signal_analysis, 'cron', hour=22, minute=15, timezone='Europe/Luxembourg')
        console.print("[green]► Signal Analysis[/green]      scheduled for [bold]22:15 CE(S)T[/bold] daily")

        scheduler.add_job(daily_ai_summaries, 'cron', hour=23, minute=30, timezone='Europe/Luxembourg')
        console.print("[green]► AI Summary Gen[/green]       scheduled for [bold]23:30 CE(S)T[/bold] daily")

        scheduler.add_job(daily_portfolio_update, 'cron', hour=23, minute=0, timezone='Europe/Luxembourg')
        console.print("[green]► Portfolio Metrics[/green]     scheduled for [bold]23:00 CE(S)T[/bold] daily")

        scheduler.add_job(daily_price_cache, 'cron', hour=1, minute=0, timezone='Europe/Luxembourg')
        console.print("[green]► Price Cache[/green]          scheduled for [bold]01:00 CE(S)T[/bold] daily")

        console.print("\n[yellow]Scheduler is active. Press Ctrl+C to exit.[/yellow]")
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            console.print("\n[dim]Scheduler stopped.[/dim]")
