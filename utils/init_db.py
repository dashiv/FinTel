"""
utils/init_db.py
----------------
Run this once to set up the database.
Safe to run again - won't delete any data.

Usage:
    python utils/init_db.py
"""
from utils.db import init_database

if __name__ == "__main__":
    init_database()
    print("\nDone! Next step:  python utils/llm.py")
