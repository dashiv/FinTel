"""One-time DB migration — adds future-proofing columns to fintel.db"""
import sqlite3, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
conn = sqlite3.connect(os.path.join(ROOT, "fintel.db"))

migrations = [
    # ipo_filings — market awareness
    ("ipo_filings", "market",      "TEXT", "US"),
    ("ipo_filings", "asset_type",  "TEXT", "ipo"),
    ("ipo_filings", "data_source", "TEXT", "sec_edgar"),   # ← source tracking

    # signals — model + market awareness
    ("signals", "model_type",  "TEXT", "ipo_scorer"),
    ("signals", "market",      "TEXT", "US"),
    ("signals", "data_source", "TEXT", "yfinance"),

    # portfolio — market awareness
    ("portfolio", "market",      "TEXT", "US"),
    ("portfolio", "data_source", "TEXT", "yfinance"),
]

for table, col, dtype, default in migrations:
    try:
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {col} {dtype} DEFAULT "{default}"')
        print(f"✅ Added {table}.{col}")
    except sqlite3.OperationalError:
        print(f"⏭  Already exists: {table}.{col}")

conn.commit()
conn.close()
print("\nMigration complete.")
