import requests, re
from datetime import datetime, timedelta

headers = {"User-Agent": "FinTel Research Tool uniquestar333@gmail.com"}

# Calculate date 30 days ago
start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
end_date = datetime.now().strftime("%Y-%m-%d")

url = f"https://efts.sec.gov/LATEST/search-index?q=%22S-1%22&dateRange=custom&startdt={start_date}&enddt={end_date}&forms=S-1&hits.hits.total.value=20"

resp = requests.get(url, headers=headers, timeout=15)
data = resp.json()

hits = data.get("hits", {}).get("hits", [])
print(f"Total filings found: {data['hits']['total']['value']}")
print(f"Showing first {len(hits)} results:\n")

for hit in hits[:10]:
    source = hit.get("_source", {})
    raw_name = source.get("display_names", ["Unknown"])[0]
    # Extract clean name: "HCW Biologics Inc. (HCWB) (CIK 0001828673)" → "HCW Biologics Inc."
    clean_name = re.split(r'\s+\(', raw_name)[0].strip()
    file_date  = source.get("file_date", "unknown")
    form_type  = source.get("root_forms", ["?"])[0]
    print(f"{form_type} | {file_date} | {clean_name}")
