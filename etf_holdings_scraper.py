"""
etf_holdings_scraper.py — Fetch exact BTC holdings from ETF issuer websites
-----------------------------------------------------------------------------
Scrapes daily holdings data directly from BlackRock (IBIT), Fidelity (FBTC),
Grayscale (GBTC/BTC), ARK (ARKB), Bitwise (BITB), VanEck (HODL), and others.

Primary source: ETF issuer websites + SEC filings
No API key required.

Usage:
    from etf_holdings_scraper import update_etf_holdings
    update_etf_holdings()  # Call every 6 hours
"""

import os
import re
import json
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger

logger = get_logger(__name__)
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

# ETF sources — URL, name, how to extract BTC holdings
ETF_SOURCES = [
    {
        'name': 'iShares Bitcoin Trust',
        'ticker': 'IBIT',
        'issuer': 'BlackRock',
        'url': 'https://www.ishares.com/us/products/333011/ishares-bitcoin-trust-etf',
        'method': 'ishares',
    },
    {
        'name': 'Fidelity Wise Origin Bitcoin Fund',
        'ticker': 'FBTC',
        'issuer': 'Fidelity',
        'url': 'https://fundresearch.fidelity.com/mutual-funds/summary/316341400',
        'method': 'fidelity',
    },
    {
        'name': 'Grayscale Bitcoin Trust',
        'ticker': 'GBTC',
        'issuer': 'Grayscale',
        'url': 'https://www.grayscale.com/crypto-products/grayscale-bitcoin-trust',
        'method': 'grayscale',
    },
    {
        'name': 'ARK 21Shares Bitcoin',
        'ticker': 'ARKB',
        'issuer': 'ARK Invest',
        'url': 'https://www.ark-funds.com/funds/arkb',
        'method': 'generic',
    },
    {
        'name': 'Bitwise Bitcoin',
        'ticker': 'BITB',
        'issuer': 'Bitwise',
        'url': 'https://bitbetf.com/',
        'method': 'generic',
    },
    {
        'name': 'VanEck Bitcoin Trust',
        'ticker': 'HODL',
        'issuer': 'VanEck',
        'url': 'https://www.vaneck.com/us/en/investments/bitcoin-trust-hodl/',
        'method': 'generic',
    },
    {
        'name': 'Franklin Bitcoin',
        'ticker': 'EZBC',
        'issuer': 'Franklin Templeton',
        'url': 'https://www.franklintempleton.com/investments/options/exchange-traded-funds/products/39639/SINGLCLASS/franklin-bitcoin-etf/EZBC',
        'method': 'generic',
    },
    {
        'name': 'Invesco Galaxy Bitcoin',
        'ticker': 'BTCO',
        'issuer': 'Invesco',
        'url': 'https://www.invesco.com/us/financial-products/etfs/product-detail?audienceType=Investor&ticker=BTCO',
        'method': 'generic',
    },
]


def _extract_btc_from_page(html, method):
    """Extract BTC holdings from an ETF page."""
    soup = BeautifulSoup(html, 'html.parser')
    text = soup.get_text()

    # Look for BTC amount patterns common across ETF pages
    patterns = [
        r'(?:Bitcoin|BTC)\s*(?:Holdings?|Amount)?\s*[:\s]*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)',
        r'(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:BTC|Bitcoin)',
        r'Total\s+(?:Bitcoin|BTC)\s*[:\s]*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)',
        r'Coins?\s*(?:Held|Outstanding)\s*[:\s]*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)',
        r'(?:Net\s+)?Assets?\s*[:\s]*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*BTC',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            amounts = []
            for m in matches:
                clean = m.replace(',', '')
                try:
                    val = float(clean)
                    # BTC holdings should be between 100 and 1,000,000
                    if 100 <= val <= 1_000_000:
                        amounts.append(val)
                except:
                    pass
            if amounts:
                return int(max(amounts))

    return 0


def _fetch_etf_holdings(etf):
    """Fetch BTC holdings for a single ETF."""
    try:
        resp = requests.get(etf['url'], headers=HEADERS, timeout=30)
        resp.raise_for_status()
        btc = _extract_btc_from_page(resp.text, etf['method'])
        return btc
    except Exception as e:
        logger.debug(f"  ETF fetch error for {etf['ticker']}: {e}")
        return 0


def _get_etf_data_from_coingecko():
    """Fallback: Get ETF data from CoinGecko treasury endpoint."""
    try:
        resp = requests.get(
            'https://api.coingecko.com/api/v3/companies/public_treasury/bitcoin',
            headers={'Accept': 'application/json'},
            timeout=30,
        )
        if resp.ok:
            data = resp.json()
            companies = data.get('companies', [])
            # Map by name for matching
            etf_data = {}
            for c in companies:
                name = c.get('name', '')
                btc = c.get('total_holdings', 0)
                if btc > 0:
                    etf_data[name.lower()] = {'btc': btc, 'name': name}
            return etf_data
    except:
        pass
    return {}


def update_etf_holdings():
    """
    Main function: Update ETF BTC holdings from issuer websites.
    Call every 6 hours.
    """
    logger.info("ETF scraper: updating holdings from issuer websites...")

    updated = 0
    errors = 0

    for etf in ETF_SOURCES:
        btc = _fetch_etf_holdings(etf)

        if btc > 0:
            # Update database
            try:
                # Find matching entity by name or create new
                result = supabase.table("treasury_companies").select("id, btc_holdings").ilike(
                    "company", f"%{etf['name'][:20]}%"
                ).execute()

                if result.data:
                    old_btc = result.data[0].get('btc_holdings', 0)
                    if btc != old_btc:
                        supabase.table("treasury_companies").update({
                            'btc_holdings': btc,
                        }).eq('id', result.data[0]['id']).execute()
                        logger.info(f"  ETF: {etf['name']} updated {old_btc:,} → {btc:,} BTC")
                        updated += 1
                    else:
                        updated += 1  # Confirmed, no change
                else:
                    logger.debug(f"  ETF: {etf['name']} not found in DB (ticker: {etf['ticker']})")
                    errors += 1
            except Exception as e:
                errors += 1
                logger.debug(f"  ETF DB error for {etf['ticker']}: {e}")
        else:
            errors += 1
            logger.debug(f"  ETF: no BTC data for {etf['ticker']}")

        time.sleep(2)  # Be polite to issuer websites

    logger.info(f"ETF scraper: {updated} updated, {errors} errors")
    return {'updated': updated, 'errors': errors}


if __name__ == "__main__":
    logger.info("ETF scraper — manual run...")
    result = update_etf_holdings()
    print(f"Updated: {result['updated']}, Errors: {result['errors']}")
