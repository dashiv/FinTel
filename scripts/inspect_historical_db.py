# scripts/inspect_historical_db.py
import sqlite3, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
conn = sqlite3.connect(os.path.join(ROOT, "fintel_historical.db"))
print("=== historical_ipos columns ===")
for row in conn.execute("PRAGMA table_info(historical_ipos)").fetchall():
    print(f"  {row[1]:30s} {row[2]}")
print("\n=== price_checkpoints columns ===")
for row in conn.execute("PRAGMA table_info(price_checkpoints)").fetchall():
    print(f"  {row[1]:30s} {row[2]}")
print("\n=== Sample row ===")
row = conn.execute("SELECT * FROM historical_ipos LIMIT 1").fetchone()
desc = conn.execute("PRAGMA table_info(historical_ipos)").fetchall()
if row:
    for col, val in zip([d[1] for d in desc], row):
        print(f"  {col:30s} = {val}")
conn.close()
