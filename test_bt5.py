import requests
from bs4 import BeautifulSoup

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

urls = [
    ('https://bitcointreasuries.net/', 'public'),
    ('https://bitcointreasuries.net/private-companies', 'private'),
    ('https://bitcointreasuries.net/etf-and-funds', 'etf'),
    ('https://bitcointreasuries.net/defi-and-other', 'defi'),
    ('https://bitcointreasuries.net/governments', 'governments'),
]

for url, label in urls:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, 'lxml')
        tables = soup.find_all('table')
        total_rows = sum(len(t.find_all('tr')) - 1 for t in tables)
        h1 = soup.find('h1')
        h1_text = h1.get_text(strip=True)[:60] if h1 else 'no h1'
        print(f'{label:15s} status={r.status_code} tables={len(tables)} rows={total_rows:>4} h1="{h1_text}"')
        if tables and total_rows > 0:
            biggest = max(tables, key=lambda t: len(t.find_all('tr')))
            row = biggest.find_all('tr')[1]
            cols = [td.get_text(strip=True)[:25] for td in row.find_all('td')]
            print(f'                first: {cols[:6]}')
    except Exception as e:
        print(f'{label:15s} FAIL: {str(e)[:60]}')
