"""
whale_monitor.py — Large BTC Transaction Monitor
--------------------------------------------------
Monitors the Bitcoin blockchain for large transactions (100+ BTC)
using free public APIs. Cross-references known corporate/government
wallet addresses.

Primary source: blockchain.info, blockchair.com (free APIs)

Usage:
    from whale_monitor import check_whale_transactions
    check_whale_transactions()  # Call every 15 minutes
"""

import os
import requests
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger

logger = get_logger(__name__)
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_PAID_CHANNEL_ID = os.getenv("TELEGRAM_PAID_CHANNEL_ID")

# Minimum BTC to trigger alert
MIN_BTC_ALERT = 500

# Known corporate/government wallet labels
# These are well-known addresses tracked by Arkham Intelligence
KNOWN_WALLETS = {
    # US Government (seized BTC)
    'bc1qa5wkgaew2dkv56kc6hp23': {'entity': 'US Government', 'type': 'government'},
    # El Salvador
    'bc1qhtrr5fhqkfmd9': {'entity': 'El Salvador', 'type': 'government'},
    # Strategy/MicroStrategy
    'bc1qazcm763858nkj2dj986etajv6wquslv8uxwczt': {'entity': 'Strategy (MSTR)', 'type': 'public_company'},
    # Grayscale GBTC
    'bc1qjasf9z3h7w3jspkhtg': {'entity': 'Grayscale GBTC', 'type': 'etf'},
    # iShares IBIT
    'bc1q0lhx5x5t6lqm': {'entity': 'iShares IBIT', 'type': 'etf'},
}

HEADERS = {
    'User-Agent': 'TreasurySignalIntelligence/1.0',
    'Accept': 'application/json',
}


def _get_recent_large_txs():
    """Fetch recent large BTC transactions from blockchain.info."""
    transactions = []

    try:
        # Method 1: blockchain.info latest blocks
        resp = requests.get('https://blockchain.info/latestblock', headers=HEADERS, timeout=15)
        if resp.ok:
            latest = resp.json()
            block_hash = latest.get('hash', '')

            if block_hash:
                block_resp = requests.get(
                    f'https://blockchain.info/rawblock/{block_hash}',
                    headers=HEADERS, timeout=30,
                )
                if block_resp.ok:
                    block = block_resp.json()
                    for tx in block.get('tx', []):
                        total_output = sum(o.get('value', 0) for o in tx.get('out', [])) / 1e8
                        if total_output >= MIN_BTC_ALERT:
                            transactions.append({
                                'tx_hash': tx.get('hash', ''),
                                'btc_amount': total_output,
                                'timestamp': tx.get('time', 0),
                                'inputs': [i.get('prev_out', {}).get('addr', '') for i in tx.get('inputs', []) if i.get('prev_out', {}).get('addr')],
                                'outputs': [o.get('addr', '') for o in tx.get('out', []) if o.get('addr')],
                            })
    except Exception as e:
        logger.debug(f"  Whale monitor blockchain.info error: {e}")

    # Method 2: blockchair.com large transactions
    try:
        resp = requests.get(
            'https://api.blockchair.com/bitcoin/transactions?s=output_total(desc)&limit=10',
            headers=HEADERS, timeout=15,
        )
        if resp.ok:
            data = resp.json()
            for tx in data.get('data', []):
                btc = tx.get('output_total', 0) / 1e8
                if btc >= MIN_BTC_ALERT:
                    transactions.append({
                        'tx_hash': tx.get('hash', ''),
                        'btc_amount': btc,
                        'timestamp': int(datetime.fromisoformat(tx.get('time', '2026-01-01')).timestamp()) if tx.get('time') else 0,
                        'inputs': [],
                        'outputs': [],
                    })
    except Exception as e:
        logger.debug(f"  Whale monitor blockchair error: {e}")

    return transactions


def _identify_entity(addresses):
    """Try to identify an entity from wallet addresses."""
    for addr in addresses:
        for known_prefix, info in KNOWN_WALLETS.items():
            if addr.startswith(known_prefix):
                return info
    return None


def _get_processed_txs():
    """Get already-processed transaction hashes."""
    try:
        result = supabase.table("whale_transactions").select("tx_hash").order(
            "detected_at", desc=True
        ).limit(100).execute()
        return set(r['tx_hash'] for r in (result.data or []))
    except:
        return set()


def _store_transaction(tx_data):
    """Store a whale transaction."""
    try:
        supabase.table("whale_transactions").upsert(tx_data, on_conflict="tx_hash").execute()
    except Exception as e:
        logger.debug(f"  Whale store error: {e}")


def _send_whale_alert(btc_amount, entity_name, tx_hash, direction):
    """Send Telegram alert for large BTC transaction."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_PAID_CHANNEL_ID:
        return

    emoji = '🐋' if btc_amount >= 1000 else '🦈'
    entity_str = f"\n🏢 **Identified: {entity_name}**" if entity_name else ''

    msg = f"{emoji} **WHALE ALERT**\n\n"
    msg += f"₿ **{btc_amount:,.0f} BTC** moved on-chain\n"
    msg += f"📊 Direction: {direction}{entity_str}\n"
    msg += f"\n🔗 [View Transaction](https://blockchain.info/tx/{tx_hash})\n"
    msg += f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}"

    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                'chat_id': TELEGRAM_PAID_CHANNEL_ID,
                'text': msg,
                'parse_mode': 'Markdown',
                'disable_web_page_preview': True,
            },
            timeout=10,
        )
    except:
        pass


def check_whale_transactions():
    """
    Main function: Check for large BTC transactions.
    Call every 15 minutes.
    """
    logger.info("Whale monitor: checking for large transactions...")

    processed = _get_processed_txs()
    transactions = _get_recent_large_txs()

    new_count = 0
    alerts = 0

    for tx in transactions:
        tx_hash = tx.get('tx_hash', '')
        if not tx_hash or tx_hash in processed:
            continue

        btc = tx['btc_amount']
        all_addrs = tx.get('inputs', []) + tx.get('outputs', [])
        entity = _identify_entity(all_addrs)

        # Determine direction
        input_entity = _identify_entity(tx.get('inputs', []))
        output_entity = _identify_entity(tx.get('outputs', []))

        if input_entity and not output_entity:
            direction = f"{input_entity['entity']} → Unknown"
        elif output_entity and not input_entity:
            direction = f"Unknown → {output_entity['entity']}"
        elif input_entity and output_entity:
            direction = f"{input_entity['entity']} → {output_entity['entity']}"
        else:
            direction = "Unknown → Unknown"

        entity_name = (entity or {}).get('entity', '')

        # Store
        tx_data = {
            'tx_hash': tx_hash,
            'btc_amount': btc,
            'entity_name': entity_name[:200] or None,
            'direction': direction[:200],
            'detected_at': datetime.now().isoformat(),
        }
        _store_transaction(tx_data)
        new_count += 1

        # Alert for very large transactions or identified entities
        if btc >= 1000 or entity_name:
            _send_whale_alert(btc, entity_name, tx_hash, direction)
            alerts += 1

        logger.info(f"  Whale: {btc:,.0f} BTC — {direction}")

    logger.info(f"Whale monitor: {new_count} new transactions, {alerts} alerts")
    return {'new_transactions': new_count, 'alerts': alerts}


if __name__ == "__main__":
    logger.info("Whale monitor — manual run...")
    result = check_whale_transactions()
    print(f"New: {result['new_transactions']}, Alerts: {result['alerts']}")
