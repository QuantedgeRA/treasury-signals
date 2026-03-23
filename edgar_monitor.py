"""
edgar_monitor.py
----------------
Monitors SEC EDGAR for 8-K filings from Bitcoin treasury companies.

8-K filings are "current reports" that companies must file when major
events happen - like buying Bitcoin. When Strategy buys BTC, they file
an 8-K within days. This monitor catches those filings automatically.

Uses SEC's free EDGAR API - no API key required.
"""

import requests
import time
from datetime import datetime, timedelta
from logger import get_logger
from freshness_tracker import freshness

logger = get_logger(__name__)

# SEC requires a User-Agent header with your name and email
SEC_HEADERS = {
    "User-Agent": "TreasurySignals/1.0 (treasury-signals@example.com)",
    "Accept-Encoding": "gzip, deflate",
}

# CIK numbers for Bitcoin treasury companies
TREASURY_COMPANIES = {
    "0001050446": {"name": "Strategy (MSTR)", "ticker": "MSTR", "priority": "high"},
    "0001507605": {"name": "MARA Holdings", "ticker": "MARA", "priority": "high"},
    "0001828937": {"name": "Riot Platforms", "ticker": "RIOT", "priority": "medium"},
    "0001679788": {"name": "CleanSpark", "ticker": "CLSK", "priority": "medium"},
    "0001318605": {"name": "Tesla", "ticker": "TSLA", "priority": "low"},
    "0001326380": {"name": "Coinbase Global", "ticker": "COIN", "priority": "medium"},
    "0001547903": {"name": "Hut 8 Mining", "ticker": "HUT", "priority": "medium"},
    "0001326160": {"name": "GameStop", "ticker": "GME", "priority": "low"},
    "0001725134": {"name": "Core Scientific", "ticker": "CORZ", "priority": "medium"},
    "0001751098": {"name": "Bitfarms", "ticker": "BITF", "priority": "low"},
    "0001841175": {"name": "KULR Technology", "ticker": "KULR", "priority": "medium"},
}

# Keywords that indicate a Bitcoin purchase in 8-K filings
BTC_PURCHASE_KEYWORDS = [
    "bitcoin", "btc", "digital asset", "cryptocurrency",
    "acquired", "purchased", "acquisition of",
    "treasury", "reserve asset",
    "strc", "preferred stock", "at-the-market",
]


def get_recent_filings(cik, filing_type="8-K"):
    """
    Fetch recent filings for a company from SEC EDGAR.
    """
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"

    try:
        response = requests.get(url, headers=SEC_HEADERS, timeout=15)

        if response.status_code == 200:
            data = response.json()

            recent = data.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            dates = recent.get("filingDate", [])
            accessions = recent.get("accessionNumber", [])
            primary_docs = recent.get("primaryDocument", [])
            descriptions = recent.get("primaryDocDescription", [])

            filings = []
            for i in range(min(len(forms), 20)):
                if forms[i] == filing_type:
                    accession_clean = accessions[i].replace("-", "")
                    filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{accession_clean}/{primary_docs[i]}"

                    filings.append({
                        "form": forms[i],
                        "date": dates[i],
                        "accession": accessions[i],
                        "url": filing_url,
                        "description": descriptions[i] if i < len(descriptions) else "",
                    })

            return filings
        elif response.status_code == 429:
            logger.warning(f"SEC EDGAR rate limited for CIK {cik}")
            return []
        else:
            logger.error(f"SEC EDGAR returned {response.status_code} for CIK {cik}")
            return []

    except requests.exceptions.Timeout:
        logger.error(f"SEC EDGAR request timed out for CIK {cik}")
        return []
    except requests.exceptions.ConnectionError:
        logger.error(f"SEC EDGAR connection failed for CIK {cik}")
        return []
    except Exception as e:
        logger.error(f"SEC EDGAR fetch failed for CIK {cik}: {e}", exc_info=True)
        return []


def check_filing_for_btc(filing, company_info):
    """
    Check if an 8-K filing is likely about a Bitcoin purchase.
    """
    description = filing.get("description", "").lower()

    keyword_matches = []
    for kw in BTC_PURCHASE_KEYWORDS:
        if kw in description:
            keyword_matches.append(kw)

    is_high_priority = company_info.get("priority") == "high"

    # Try to fetch the first few KB of the filing to check content
    try:
        time.sleep(0.5)  # SEC rate limit: 10 requests per second
        response = requests.get(filing["url"], headers=SEC_HEADERS, timeout=10)
        if response.status_code == 200:
            content_lower = response.text[:5000].lower()
            for kw in BTC_PURCHASE_KEYWORDS:
                if kw in content_lower and kw not in keyword_matches:
                    keyword_matches.append(kw)
    except Exception as e:
        logger.debug(f"Could not fetch filing content for keyword check: {e}")

    is_btc_related = len(keyword_matches) > 0

    return {
        "is_btc_related": is_btc_related,
        "is_high_priority": is_high_priority,
        "keyword_matches": keyword_matches,
        "should_alert": is_btc_related or is_high_priority,
    }


def scan_edgar_filings(days_back=3):
    """
    Scan all tracked companies for recent 8-K filings.
    """
    cutoff_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    noteworthy = []

    for cik, company_info in TREASURY_COMPANIES.items():
        name = company_info["name"]
        logger.debug(f"Checking {name} on EDGAR...")

        time.sleep(0.2)  # SEC rate limit
        filings = get_recent_filings(cik, "8-K")

        recent_8ks = [f for f in filings if f["date"] >= cutoff_date]

        if recent_8ks:
            logger.info(f"EDGAR: {name} has {len(recent_8ks)} recent 8-K(s)")
            for filing in recent_8ks:
                analysis = check_filing_for_btc(filing, company_info)

                if analysis["should_alert"]:
                    noteworthy.append({
                        "company": name,
                        "ticker": company_info["ticker"],
                        "priority": company_info["priority"],
                        "date": filing["date"],
                        "url": filing["url"],
                        "description": filing["description"],
                        "is_btc_related": analysis["is_btc_related"],
                        "keyword_matches": analysis["keyword_matches"],
                    })
        else:
            logger.debug(f"EDGAR: {name} — no recent 8-K filings")

    if noteworthy:
        logger.info(f"EDGAR scan complete: {len(noteworthy)} noteworthy filing(s)")
        freshness.record_success("sec_edgar", detail=f"{len(noteworthy)} noteworthy filing(s)")
    else:
        logger.info("EDGAR scan complete: no noteworthy filings")
        freshness.record_success("sec_edgar", detail="No noteworthy filings")

    return noteworthy


def format_edgar_alert(filing):
    """Format a Telegram alert for a detected SEC filing."""

    if filing["is_btc_related"]:
        emoji = "🚨"
        label = "BITCOIN-RELATED 8-K FILING"
    else:
        emoji = "📋"
        label = "NEW 8-K FILING (High-Priority Company)"

    keywords_text = ", ".join(filing["keyword_matches"]) if filing["keyword_matches"] else "None detected"

    return f"""
{emoji} SEC FILING DETECTED: {label}

🏢 Company: {filing['company']} (${filing['ticker']})
📅 Filed: {filing['date']}
📄 Description: {filing['description'][:200]}

🔑 BTC Keywords Found: {keywords_text}

🔗 Filing: {filing['url']}

Why this matters:
8-K filings disclose material events like Bitcoin purchases.
Strategy typically files 8-K within 1-2 days of buying BTC.

---
Treasury Purchase Signal Intelligence
"""


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    logger.info("SEC EDGAR Filing Monitor — scanning...")

    noteworthy = scan_edgar_filings(days_back=7)

    if noteworthy:
        for filing in noteworthy:
            btc_label = "BTC" if filing['is_btc_related'] else "8-K"
            logger.info(
                f"[{btc_label}] {filing['company']} ({filing['ticker']}) — "
                f"Filed {filing['date']} — Keywords: {', '.join(filing['keyword_matches']) or 'None'}"
            )
    else:
        logger.info("No noteworthy 8-K filings found in the last 7 days")

    logger.info("EDGAR Monitor test complete")
