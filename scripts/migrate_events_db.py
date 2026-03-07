"""Adds market + region scope to fintel_events.db"""
import sqlite3, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
conn = sqlite3.connect(os.path.join(ROOT, "fintel_events.db"))
for table in ["market_events", "market_regimes", "tech_cycles"]:
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN market TEXT DEFAULT 'US'")
        conn.execute(f"ALTER TABLE {table} ADD COLUMN region TEXT DEFAULT 'north_america'")
        print(f"✅ {table}")
    except:
        print(f"⏭  {table} already migrated")
conn.commit()
conn.close()
print("Events DB migration complete.")
