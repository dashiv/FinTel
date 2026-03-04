import os
import tempfile
import sqlite3

import pytest

from utils import db


def setup_temp_db():
    tf = tempfile.NamedTemporaryFile(delete=False)
    tf.close()
    db.DB_PATH = tf.name
    db.init_database()
    return tf.name


def teardown_temp_db(path):
    try:
        os.unlink(path)
    except Exception:
        pass


def test_watchlist_and_portfolio_helpers():
    path = setup_temp_db()
    try:
        # insert a filing and add to watchlist
        conn = db.get_connection()
        c = conn.cursor()
        c.execute("INSERT INTO ipo_filings(company_name, ticker, interest_score) VALUES (?, ?, ?)",
                  ("TestCo", "TST", 80))
        filing_id = c.lastrowid
        conn.commit()
        conn.close()

        assert not db.is_in_watchlist(filing_id)
        wid = db.add_to_watchlist(filing_id, conviction_score=85)
        assert wid > 0
        assert db.is_in_watchlist(filing_id)

        wl = db.get_watchlist()
        assert len(wl) == 1 and wl[0]['filing_id'] == filing_id

        # add to portfolio and then close
        pid = db.add_position("TST", "TestCo", "2026-03-01", 10.0, 5)
        assert pid > 0
        # simulate closing
        success = db.close_position(pid, "2026-03-10", 12.0)
        assert success
        closed = db.get_closed_positions()
        assert len(closed) == 1
        assert closed[0]['realised_pnl_pct'] == pytest.approx(20.0)
        assert closed[0]['realised_pnl_eur'] == pytest.approx(10.0)
    finally:
        teardown_temp_db(path)


def test_ai_summary_generation(monkeypatch):
    # use a fresh temporary database so tests stay isolated
    path = setup_temp_db()
    try:
        # monkeypatch LLM to return fixed text
        from utils import llm

        monkeypatch.setattr(llm, 'ask_llm', lambda prompt, model=None, temperature=0.1: "This is a summary.")
        # create dummy filing
        filing = {'company_name': 'Foo Inc', 'ticker': 'FOO', 'primary_sector': 'tech',
                  'interest_score': 75, 'filing_date': '2026-03-05'}
        summary = llm.generate_company_summary(filing)
        assert "summary" in summary.lower() or len(summary) > 0

        # test DB setter/getter
        # create a filing row so the update has something to touch
        conn = db.get_connection()
        c = conn.cursor()
        c.execute("INSERT INTO ipo_filings(company_name, ticker, interest_score) VALUES (?, ?, ?)",
                  (filing['company_name'], filing['ticker'], filing['interest_score']))
        fid = c.lastrowid
        conn.commit()
        conn.close()

        assert db.set_ai_summary(fid, summary)
        assert db.get_ai_summary(fid) == summary
    finally:
        teardown_temp_db(path)
