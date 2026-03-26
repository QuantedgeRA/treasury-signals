import requests

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

urls = [
    'https://bitcointreasuries.net/private',
    'https://bitcointreasuries.net/countries',
    'https://bitcointreasuries.net/etf',
    'https://bitcointreasuries.net/defi',
    'https://bitcointreasuries.net/funds',
    'https://bitcointreasuries.net/governments',
    'https://bitcointreasuries.net/entities?type=private',
    'https://bitcointreasuries.net/entities?type=etf',
    'https://bitcointreasuries.net/entities?type=country',
    'https://bitcointreasuries.net/entities?type=defi',
    'https://bitcointreasuries.net/?type=private',
    'https://bitcointreasuries.net/?category=private',
]

for url in urls:
    try:
        r = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        is404 = '404' in r.text[:500].lower() or r.status_code == 404
        label = 'FOUND' if r.status_code == 200 and not is404 else 'MISS'
        print(f'  {label} [{r.status_code}] {len(r.text):>8} chars  {url}')
    except Exception as e:
        print(f'  FAIL {url} -> {str(e)[:60]}')