"""
probe_feeds.py — One-shot diagnostic for candidate regulatory feed URLs.

Hits each candidate, reports HTTP status, Content-Type, body size, and either
<item> count (for XML/RSS/Atom) or top-level keys (for JSON). Used to decide
which sources have stable feeds we can replace HTML scrapers with.
"""

import re
import sys
import json
import time
import requests
from urllib.parse import urlparse

HEADERS = {
    'User-Agent': 'TreasurySignalIntelligence admin@quantedgeriskadvisory.com',
    'Accept': 'application/rss+xml, application/atom+xml, application/xml, application/json, text/html;q=0.5',
}

# Candidate feed URLs — multiple per source so we discover what works.
# Each tuple: (label, url, expected_format)
CANDIDATES = [
    # 1. USA — SEC EDGAR
    ("USA/EDGAR atom (current 8-K)", "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&output=atom", "atom"),
    ("USA/EDGAR FTS json (bitcoin)", "https://efts.sec.gov/LATEST/search-index?q=%22bitcoin%22&forms=8-K", "json"),

    # 2. Canada — SEDAR+
    ("Canada/SEDAR+ search html", "https://www.sedarplus.ca/csa-party/records/document.html?id=&keywords=bitcoin", "html"),
    ("Canada/SEDAR+ filings api", "https://www.sedarplus.ca/landingpage/api/v1/recent-filings?keyword=bitcoin", "json"),

    # 3. Japan — TDnet / EDINET
    ("Japan/EDINET json", "https://disclosure.edinet-fsa.go.jp/api/v2/documents.json?date=2026-05-05&type=2", "json"),
    ("Japan/TDnet daily", "https://www.release.tdnet.info/inbs/I_list_001_20260505.html", "html"),

    # 4. South Korea — DART / KIND
    ("Korea/KIND html", "https://kind.krx.co.kr/disclosure/details.do", "html"),

    # 5. France — AMF
    ("France/AMF news rss", "https://www.amf-france.org/en/rss/news", "rss"),
    ("France/AMF actualites rss", "https://www.amf-france.org/fr/rss/actualites", "rss"),

    # 6. UK — RNS / LSE / Investegate
    ("UK/Investegate rss", "https://www.investegate.co.uk/Rss.aspx?type=rss&searchKeyword=bitcoin", "rss"),
    ("UK/Investegate company rss", "https://www.investegate.co.uk/Rss.aspx?type=rss", "rss"),
    ("UK/LSE news rss", "https://www.londonstockexchange.com/news?tab=news-explorer&q=bitcoin&rss=true", "rss"),

    # 7. Germany — DGAP / EQS news / Bundesanzeiger
    ("Germany/EQS rss", "https://www.eqs-news.com/news/rss", "rss"),
    ("Germany/Bundesanzeiger search", "https://www.bundesanzeiger.de/pub/de/suchergebnis?fulltext=bitcoin&area=FinanzKapitalMarkt", "html"),

    # 8. Hong Kong — HKEX
    ("HK/HKEX listings rss", "https://www.hkexnews.hk/rss/listings.htm", "rss"),
    ("HK/HKEX titlesearch rss", "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=en&q=bitcoin", "html"),

    # 9. Australia — ASX
    ("AU/ASX announcements rss", "https://www.asx.com.au/asx/asx-announcements.xml", "rss"),
    ("AU/ASX market announcements", "https://www.asx.com.au/asx/v2/statistics/todayAnns.do", "json"),

    # 10. Brazil — CVM
    ("Brazil/CVM rss noticias", "https://conteudo.cvm.gov.br/noticias/rss.xml", "rss"),
    ("Brazil/CVM ipe", "https://www.rad.cvm.gov.br/ENET/frmConsultaExternaCVM.aspx", "html"),

    # 11. India — BSE / NSE
    ("India/BSE corp filings xml", "https://www.bseindia.com/xml-data/corpfiling/AttachLive/CFlast.xml", "xml"),
    ("India/BSE notices xml", "https://www.bseindia.com/data/xml/notices.xml", "xml"),

    # 12. Singapore — SGX
    ("SG/SGX announcements rss", "https://www.sgx.com/wcm/connect/sgx_en/home/announcements/rss", "rss"),
    ("SG/SGX api search", "https://api.sgx.com/announcements/v1.1/?keyword=bitcoin&pagesize=50", "json"),

    # 13. Israel — TASE / Maya
    ("Israel/TASE Maya rss", "https://maya.tase.co.il/api/v1/syndication/RssService", "rss"),

    # 14. Norway — Oslo Bors / Euronext newsweb
    ("Norway/Newsweb rss", "https://newsweb.oslobors.no/rss/getRssFeed", "rss"),
    ("Norway/Newsweb messages json", "https://api3.oslo.oslobors.no/v1/newsfeed/messages?market=OSE", "json"),
    ("Norway/Euronext news rss", "https://live.euronext.com/en/rss/news", "rss"),

    # 15. Sweden — FI / Nasdaq Stockholm
    ("Sweden/FI sv rss", "https://www.fi.se/sv/rss/marknadsinformation/", "rss"),
    ("Sweden/Nasdaq nordic rss", "https://www.nasdaqomxnordic.com/news/companynews/rss?lang=en", "rss"),

    # 16. Turkey — KAP
    ("Turkey/KAP rss", "https://www.kap.org.tr/en/rss/general", "rss"),
    ("Turkey/KAP rss tr", "https://www.kap.org.tr/tr/rss", "rss"),

    # 17. El Salvador
    ("El Salvador dashboard html", "https://bitcoin.gob.sv", "html"),
]


def probe(label, url, expected):
    out = {"label": label, "url": url, "expected": expected, "ok": False}
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        out["status"] = resp.status_code
        out["final_url"] = resp.url
        out["content_type"] = resp.headers.get("Content-Type", "")
        out["bytes"] = len(resp.content)

        body = resp.text or ""
        ct = out["content_type"].lower()

        # Detect actual format from response
        if "json" in ct or body.strip().startswith(("{", "[")):
            out["format"] = "json"
            try:
                data = resp.json()
                if isinstance(data, dict):
                    out["json_top_keys"] = list(data.keys())[:10]
                elif isinstance(data, list):
                    out["json_list_len"] = len(data)
            except Exception as e:
                out["json_parse_error"] = str(e)[:80]
        elif "<rss" in body[:500].lower() or "<feed" in body[:500].lower() or "xml" in ct:
            out["format"] = "rss/atom" if ("<rss" in body[:500].lower() or "<feed" in body[:500].lower()) else "xml"
            item_count = len(re.findall(r"<item\b", body, re.IGNORECASE)) or len(re.findall(r"<entry\b", body, re.IGNORECASE))
            out["item_count"] = item_count
            # Check if "bitcoin" appears anywhere in feed body
            out["bitcoin_in_body"] = bool(re.search(r"bitcoin|btc\b", body, re.IGNORECASE))
        else:
            out["format"] = "html"
            # Look for obvious markers
            out["html_has_bitcoin"] = bool(re.search(r"bitcoin|btc\b", body, re.IGNORECASE))
            out["html_title"] = (re.search(r"<title>([^<]+)</title>", body, re.IGNORECASE).group(1)[:120]
                                 if re.search(r"<title>([^<]+)</title>", body, re.IGNORECASE) else "")
            # Heuristic: SPA pages tend to be small and contain a root div
            out["looks_like_spa"] = "id=\"root\"" in body or "id=\"app\"" in body or len(body) < 5000

        out["ok"] = resp.status_code == 200
        out["preview"] = body[:200].replace("\n", " ").replace("\r", " ")
    except Exception as e:
        out["error"] = str(e)[:200]
    return out


def main():
    print(f"Probing {len(CANDIDATES)} candidate feed URLs...\n")
    results = []
    for label, url, expected in CANDIDATES:
        r = probe(label, url, expected)
        results.append(r)
        status = r.get("status", "ERR")
        fmt = r.get("format", r.get("error", "?"))
        nbytes = r.get("bytes", 0)
        items = r.get("item_count", "")
        items_str = f" items={items}" if items != "" else ""
        bitcoin = "+btc" if r.get("bitcoin_in_body") or r.get("html_has_bitcoin") else ""
        print(f"  [{status}] {label:42s} fmt={fmt:10s} bytes={nbytes:>7}{items_str} {bitcoin}")
        time.sleep(0.4)

    # Summary table
    print("\n" + "=" * 100)
    print("FULL JSON DUMP")
    print("=" * 100)
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
