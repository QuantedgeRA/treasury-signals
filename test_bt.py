import requests
from bs4 import BeautifulSoup

r = requests.get('https://bitcointreasuries.net/', headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
soup = BeautifulSoup(r.text, 'lxml')

# Find all section headers
print("=== SECTION HEADERS ===")
for tag in soup.find_all(['h1','h2','h3']):
    text = tag.get_text(strip=True)[:80]
    if text:
        print(f"  {tag.name}: {text}")

# Table details
print("\n=== TABLES ===")
tables = soup.find_all('table')
total_rows = 0
for i, t in enumerate(tables):
    rows = t.find_all('tr')
    total_rows += len(rows) - 1
    print(f"  Table {i}: {len(rows)-1} data rows")
    # Show first 3 rows
    for row in rows[1:4]:
        cols = [td.get_text(strip=True)[:25] for td in row.find_all('td')]
        print(f"    {cols[:7]}")

print(f"\nTotal data rows across all tables: {total_rows}")
