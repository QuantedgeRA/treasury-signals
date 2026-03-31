"""
defi_tracker.py — DeFi Protocol BTC Holdings via DeFi Llama API
-----------------------------------------------------------------
Fetches real-time BTC holdings from DeFi protocols using the free
DeFi Llama API. Covers WBTC, BTCB, Solv Protocol, Lombard, etc.

Primary source: https://api.llama.fi (free, no API key)

Usage:
    from defi_tracker import update_defi_holdings
    update_defi_holdings()  # Call every 6 hours
"""

import os
import re
import requests
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger

logger = get_logger(__name__)
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# DeFi protocols that hold/wrap BTC
DEFI_PROTOCOLS = [
    {'slug': 'wbtc', 'name': 'Wrapped BTC (WBTC)', 'db_match': 'Wrapped'},
    {'slug': 'btcb', 'name': 'BTCB (Binance)', 'db_match': 'BTCB'},
    {'slug': 'solv-protocol', 'name': 'Solv Protocol', 'db_match': 'Solv'},
    {'slug': 'lombard', 'name': 'Lombard Protocol (LBTC)', 'db_match': 'Lombard'},
    {'slug': 'threshold-btc', 'name': 'Threshold BTC (tBTC)', 'db_match': 'Threshold'},
    {'slug': 'avalanche-bridged-btc', 'name': 'Avalanche Bridged BTC', 'db_match': 'Avalanche'},
    {'slug': 'dlcbtc', 'name': 'DLC.Link BTC', 'db_match': 'DLC'},
]

HEADERS = {
    'Accept': 'application/json',
    'User-Agent': 'TreasurySignalIntelligence/1.0',
}

BTC_PRICE_CACHE = {'price': 0, 'updated': 0}


def _get_btc_price():
    """Get current BTC price for TVL-to-BTC conversion."""
    now = datetime.now().timestamp()
    if BTC_PRICE_CACHE['price'] > 0 and (now - BTC_PRICE_CACHE['updated']) < 300:
        return BTC_PRICE_CACHE['price']

    try:
        resp = requests.get('https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd', timeout=10)
        if resp.ok:
            price = resp.json().get('bitcoin', {}).get('usd', 0)
            if price > 0:
                BTC_PRICE_CACHE['price'] = price
                BTC_PRICE_CACHE['updated'] = now
                return price
    except:
        pass
    return BTC_PRICE_CACHE.get('price', 67000)


def _fetch_protocol_tvl(slug):
    """Fetch TVL from DeFi Llama for a protocol."""
    try:
        resp = requests.get(f'https://api.llama.fi/protocol/{slug}', headers=HEADERS, timeout=30)
        if resp.ok:
            data = resp.json()
            # Get current TVL in USD
            tvl = data.get('currentChainTvls', {})
            total_tvl = sum(v for k, v in tvl.items() if isinstance(v, (int, float)) and not k.endswith('-borrowed'))
            if total_tvl <= 0:
                total_tvl = data.get('tvl', [{}])[-1].get('totalLiquidityUSD', 0) if data.get('tvl') else 0
            return total_tvl
    except Exception as e:
        logger.debug(f"  DeFi Llama error for {slug}: {e}")
    return 0


def _fetch_all_protocols_btc():
    """Fetch BTC-specific data from DeFi Llama."""
    results = {}
    btc_price = _get_btc_price()

    for protocol in DEFI_PROTOCOLS:
        tvl_usd = _fetch_protocol_tvl(protocol['slug'])
        if tvl_usd > 0 and btc_price > 0:
            btc_equivalent = int(tvl_usd / btc_price)
            results[protocol['db_match']] = {
                'name': protocol['name'],
                'btc': btc_equivalent,
                'tvl_usd': tvl_usd,
            }
            logger.debug(f"  DeFi: {protocol['name']} — ${tvl_usd:,.0f} TVL — ~{btc_equivalent:,} BTC")

    return results


def update_defi_holdings():
    """
    Main function: Update DeFi protocol BTC holdings from DeFi Llama.
    Call every 6 hours.
    """
    logger.info("DeFi tracker: fetching holdings from DeFi Llama...")

    defi_data = _fetch_all_protocols_btc()
    if not defi_data:
        logger.warning("DeFi tracker: no data fetched")
        return {'updated': 0, 'errors': 0}

    updated = 0
    errors = 0

    for db_match, data in defi_data.items():
        try:
            # Find matching entity in database
            result = supabase.table("treasury_companies").select("id, company, btc_holdings").ilike(
                "company", f"%{db_match}%"
            ).eq("entity_type", "defi").execute()

            if result.data:
                entity = result.data[0]
                old_btc = entity.get('btc_holdings', 0)
                new_btc = data['btc']

                # Only update if significant change (>1%)
                if old_btc == 0 or abs(new_btc - old_btc) / max(old_btc, 1) > 0.01:
                    supabase.table("treasury_companies").update({
                        'btc_holdings': new_btc,
                    }).eq('id', entity['id']).execute()
                    logger.info(f"  DeFi: {entity['company']} {old_btc:,} → {new_btc:,} BTC")
                    updated += 1
                else:
                    updated += 1  # Confirmed
            else:
                logger.debug(f"  DeFi: {data['name']} not found in DB (match: {db_match})")
                errors += 1
        except Exception as e:
            errors += 1
            logger.debug(f"  DeFi DB error: {e}")

    logger.info(f"DeFi tracker: {updated} updated, {errors} errors")
    return {'updated': updated, 'errors': errors}


if __name__ == "__main__":
    logger.info("DeFi tracker — manual run...")
    result = update_defi_holdings()
    print(f"Updated: {result['updated']}, Errors: {result['errors']}")
