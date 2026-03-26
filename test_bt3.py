import requests
from bs4 import BeautifulSoup

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

urls = [
    ('https://bitcointreasuries.net/', 'main (public)'),
    ('https://bitcointreasuries.net/?type=private', 'private'),
    ('https://bitcointreasuries.net/?type=etf', 'etf'),
    ('https://bitcointreasuries.net/?type=defi', 'defi'),
    ('https://bitcointreasuries.net/governments', 'governments'),
    ('https://bitcointreasuries.net/?type=country', 'country'),
    ('https://bitcointreasuries.net/?type=fund', 'fund'),
    ('https://bitcointreasuries.net/?type=exchange', 'exchange'),
]

for url, label in urls:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            print(f'  MISS [{r.status_code}] {label}: {url}')
            continue
        soup = BeautifulSoup(r.text, 'lxml')
        tables = soup.find_all('table')
        total_rows = sum(len(t.find_all('tr')) - 1 for t in tables)
        # Find the main h1
        h1 = soup.find('h1')
        h1_text = h1.get_text(strip=True)[:50] if h1 else 'no h1'
        print(f'  OK   {label:15s} tables={len(tables)} rows={total_rows:>4}  h1="{h1_text}"')
        # Show first row of biggest table
        if tables:
            biggest = max(tables, key=lambda t: len(t.find_all('tr')))
            first_row = biggest.find_all('tr')[1] if len(biggest.find_all('tr')) > 1 else None
            if first_row:
                cols = [td.get_text(strip=True)[:20] for td in first_row.find_all('td')]
                print(f'         first row: {cols[:5]}')
    except Exception as e:
        print(f'  FAIL {label}: {str(e)[:60]}')
