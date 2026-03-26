import requests
import re
import json

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

r = requests.get('https://bitcointreasuries.net/', headers=HEADERS, timeout=15)
text = r.text

# Look for embedded JSON data in script tags
print(f"Page size: {len(text)} chars")

# Search for common patterns of embedded data
patterns = [
    r'__NEXT_DATA__.*?({.*?})\s*</script>',
    r'window\.__data\s*=\s*({.*?});',
    r'window\.__INITIAL_STATE__\s*=\s*({.*?});',
    r'"entities"\s*:\s*\[',
    r'"private"\s*:\s*\[',
    r'"etf"\s*:\s*\[',
    r'"defi"\s*:\s*\[',
    r'"companies"\s*:\s*\[',
]

for pat in patterns:
    matches = re.findall(pat, text[:500000], re.DOTALL)
    if matches:
        print(f"  FOUND pattern: {pat[:40]}  matches={len(matches)}")
        for m in matches[:1]:
            preview = m[:200] if isinstance(m, str) else str(m)[:200]
            print(f"    preview: {preview}")
    else:
        # Try simpler search
        if pat.startswith(r'"'):
            simple = pat.replace('\\', '').replace(r'\s*', '').replace(r'\[', '[')
            count = text.count(simple.strip('"').split('"')[0])
            if count > 0:
                print(f"  PARTIAL: found '{simple[:30]}' {count} times")

# Also search for JSON arrays with bitcoin data
print("\n--- Searching for large JSON arrays ---")
for keyword in ['private_compan', 'etf_compan', 'defi', 'Private', 'ETF', 'DeFi']:
    count = text.count(keyword)
    if count > 0:
        idx = text.index(keyword)
        print(f"  '{keyword}' found {count} times, first at pos {idx}")
        print(f"    context: ...{text[max(0,idx-50):idx+80]}...")
