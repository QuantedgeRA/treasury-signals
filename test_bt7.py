import requests
from bs4 import BeautifulSoup

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
r = requests.get('https://bitcointreasuries.net/', headers=HEADERS, timeout=15)
soup = BeautifulSoup(r.text, 'lxml')

# Find all internal links
for a in soup.find_all('a', href=True):
    href = a['href']
    text = a.get_text(strip=True)[:40]
    if href.startswith('/') and text and any(k in text.lower() for k in ['etf', 'fund', 'private', 'defi', 'gov', 'public', 'compan']):
        print(f'  {href:40s} -> "{text}"')
