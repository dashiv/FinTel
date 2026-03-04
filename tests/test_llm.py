from utils import llm


def test_generate_summary_monkeypatched(monkeypatch):
    monkeypatch.setattr(llm, 'ask_llm', lambda prompt, model=None, temperature=0.3: "Fake summary.")
    filing = {'company_name': 'ABC', 'ticker': 'ABC', 'primary_sector': 'test', 'interest_score': 50, 'filing_date': '2026-03-05'}
    s = llm.generate_company_summary(filing)
    assert s == "Fake summary."
