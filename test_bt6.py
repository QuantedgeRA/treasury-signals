import requests

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

urls = [
    'https://bitcointreasuries.net/etf',
    'https://bitcointreasuries.net/etfs',
    'https://bitcointreasuries.net/funds',
    'https://bitcointreasuries.net/etf-funds',
    'https://bitcointreasuries.net/etfs-and-funds',
    'https://bitcointreasuries.net/exchange-traded-funds',
    'https://bitcointreasuries.net/bitcoin-etf',
    'https://bitcointreasuries.net/bitcoin-etfs',
]

for url in urls:
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        is404 = r.status_code == 404 or 'Not found' in r.text[:5000]
        status = 'MISS' if is404 else 'FOUND'
        print(f'  {status} [{r.status_code}] {len(r.text):>8} chars  {url}')
    except Exception as e:
        print(f'  FAIL {url}')
