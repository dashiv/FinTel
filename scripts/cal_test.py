from agents.ipo_scout import fetch_expected_listing_date, refresh_calendar_for_filings

print("date", fetch_expected_listing_date('SunPower'))
print("ref", refresh_calendar_for_filings())
