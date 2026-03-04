import sqlite3
import os

DB_PATH = "fintel.db"

def migrate_db():
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found at {DB_PATH}. Run ipo_scout first.")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    print("Starting database migration for incremental scan columns...")

    # 1. Add scan_from_date to scan_runs
    try:
        c.execute("ALTER TABLE scan_runs ADD COLUMN scan_from_date TEXT")
        print("✅ Added column: scan_from_date")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("→ Column 'scan_from_date' already exists. Skipping.")
        else:
            print(f"❌ Error adding 'scan_from_date': {e}")

    # 2. Add scan_to_date to scan_runs
    try:
        c.execute("ALTER TABLE scan_runs ADD COLUMN scan_to_date TEXT")
        print("✅ Added column: scan_to_date")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("→ Column 'scan_to_date' already exists. Skipping.")
        else:
            print(f"❌ Error adding 'scan_to_date': {e}")

    # 3. Create scan_metadata table if it doesn't exist
    print("Ensuring scan_metadata table exists...")
    c.execute("""
        CREATE TABLE IF NOT EXISTS scan_metadata (
            key        TEXT PRIMARY KEY,
            value      TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    print("✅ Verified scan_metadata table.")

    conn.commit()
    conn.close()
    print("\n🎉 Migration complete. You can now safely run incremental/historical scans!")

if __name__ == "__main__":
    migrate_db()
