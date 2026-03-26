import requests
from bs4 import BeautifulSoup

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

pages = [
    ('https://bitcointreasuries.net/private-companies', 'private'),
    ('https://bitcointreasuries.net/etfs-and-exchanges', 'etf'),
    ('https://bitcointreasuries.net/governments', 'gov'),
]

for url, label in pages:
    r = requests.get(url, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(r.text, 'lxml')
    tables = soup.find_all('table')
    print(f'\n=== {label} ({url}) ===')
    print(f'Tables: {len(tables)}')
    for ti, table in enumerate(tables):
        rows = table.find_all('tr')
        print(f'  Table {ti}: {len(rows)-1} data rows')
        # Show header
        if rows:
            ths = [th.get_text(strip=True)[:15] for th in rows[0].find_all('th')]
            print(f'    Headers: {ths}')
        # Show first 3 data rows raw
        for row in rows[1:4]:
            cols = row.find_all('td')
            raw = [td.get_text(strip=True)[:30] for td in cols]
            print(f'    Row: {raw}')
        # Show a failing row (middle of table)
        mid = len(rows) // 2
        if mid > 1:
            cols = rows[mid].find_all('td')
            raw = [td.get_text(strip=True)[:30] for td in cols]
            print(f'    Mid: {raw}')