"""One-off script to backfill expected listing dates for all filings.

Usage:
    python scripts/backfill_calendar.py [--days N]

If "--days" is given, only filings whose filing_date is within the last N days
are refreshed. This allows incremental backfill of recent data without touching
old entries.
"""

import argparse

from utils.db import init_database
from agents.ipo_scout import refresh_calendar_for_filings


def main(days: int | None):
    init_database()
    if days is not None:
        # temporarily filter by recent filings in the refresh function
        # easiest to patch by grabbing the connection and running manual SQL
        from utils.db import get_connection
        conn = get_connection()
        c = conn.cursor()
        cutoff = f"date('now','-{days} days')"
        c.execute(f"SELECT id, company_name FROM ipo_filings WHERE expected_listing_date IS NULL AND filing_date >= {cutoff}")
        rows = c.fetchall()
        conn.close()
        print(f"Refreshing {len(rows)} filings from last {days} days...")
        count = 0
        from utils.db import set_expected_listing_date
        from agents.ipo_scout import fetch_expected_listing_date
        for fid, name in rows:
            exp = fetch_expected_listing_date(name)
            if exp:
                set_expected_listing_date(fid, exp)
                count += 1
        print(f"Added dates for {count} filings")
    else:
        print("Refreshing entire calendar cache (this may take a while)…")
        count = refresh_calendar_for_filings()
        print(f"Updated {count} companies")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill IPO calendar dates")
    parser.add_argument("--days", type=int, default=None,
                        help="Only process filings from the last N days")
    args = parser.parse_args()
    main(args.days)
