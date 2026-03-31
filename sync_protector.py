"""
sync_protector.py — Protects primary source data from aggregator overwrites
============================================================================
After treasury_sync.py runs (which uses CoinGecko + BitcoinTreasuries.net),
this module restores any BTC holdings that were overwritten by aggregator data
when the entity has higher-priority primary source data.

Priority order (highest to lowest):
  100 = sec_filing (SEC EDGAR)
   90 = regulatory_filing (SEDAR, EDINET, DART, RNS, etc.)
   85 = etf_issuer (iShares, Fidelity, Grayscale websites)
   80 = government_official (bitcoin.gob.sv)
   80 = defi_onchain (DeFi Llama, Etherscan)
   60 = press_release (news articles)
   10 = aggregator (CoinGecko, BitcoinTreasuries.net) ← lowest

Usage:
    # Call AFTER treasury_sync but BEFORE other post-processing
    from sync_protector import protect_primary_data
    protect_primary_data()
"""

import os
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger

logger = get_logger(__name__)
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Snapshot of primary source data — captured before sync runs
_primary_snapshot = {}


def snapshot_primary_data():
    """
    Take a snapshot of all entities with primary source data BEFORE sync runs.
    Call this BEFORE treasury_sync.
    """
    global _primary_snapshot
    _primary_snapshot = {}

    try:
        result = supabase.table("treasury_companies").select(
            "id, company, ticker, btc_holdings, data_source, source_updated_at"
        ).neq("data_source", "aggregator").execute()

        for row in (result.data or []):
            if row.get('data_source') and row['data_source'] != 'aggregator':
                _primary_snapshot[row['id']] = {
                    'company': row['company'],
                    'ticker': row.get('ticker', ''),
                    'btc_holdings': row.get('btc_holdings', 0),
                    'data_source': row['data_source'],
                    'source_updated_at': row.get('source_updated_at'),
                }

        if _primary_snapshot:
            logger.info(f"Sync protector: snapshot of {len(_primary_snapshot)} primary-source entities saved")

    except Exception as e:
        logger.debug(f"Sync protector snapshot error: {e}")

    return len(_primary_snapshot)


def protect_primary_data():
    """
    Restore primary source BTC holdings that were overwritten by aggregator sync.
    Call this AFTER treasury_sync.
    """
    global _primary_snapshot

    if not _primary_snapshot:
        logger.debug("Sync protector: no primary snapshot to restore")
        return 0

    restored = 0

    try:
        # Get current state after sync
        ids = list(_primary_snapshot.keys())

        # Supabase doesn't support IN queries well, so batch in groups
        for i in range(0, len(ids), 50):
            batch_ids = ids[i:i+50]
            for entity_id in batch_ids:
                snap = _primary_snapshot[entity_id]

                # Get current state
                result = supabase.table("treasury_companies").select(
                    "id, btc_holdings, data_source"
                ).eq("id", entity_id).limit(1).execute()

                if not result.data:
                    continue

                current = result.data[0]

                # If aggregator sync overwrote our primary source data, restore it
                if current.get('data_source') == 'aggregator' or current.get('data_source') is None:
                    supabase.table("treasury_companies").update({
                        'btc_holdings': snap['btc_holdings'],
                        'data_source': snap['data_source'],
                        'source_updated_at': snap['source_updated_at'],
                    }).eq("id", entity_id).execute()
                    restored += 1
                    logger.debug(f"  Restored: {snap['company']} — {snap['btc_holdings']:,} BTC [{snap['data_source']}]")

                # If the sync somehow set it to aggregator but btc changed, still restore primary
                elif current.get('btc_holdings') != snap['btc_holdings'] and current.get('data_source') == 'aggregator':
                    supabase.table("treasury_companies").update({
                        'btc_holdings': snap['btc_holdings'],
                        'data_source': snap['data_source'],
                        'source_updated_at': snap['source_updated_at'],
                    }).eq("id", entity_id).execute()
                    restored += 1

    except Exception as e:
        logger.debug(f"Sync protector restore error: {e}")

    if restored > 0:
        logger.info(f"Sync protector: restored {restored} entities to primary source data")

    # Clear snapshot
    _primary_snapshot = {}
    return restored


if __name__ == "__main__":
    count = snapshot_primary_data()
    print(f"Snapshot: {count} primary-source entities")
    restored = protect_primary_data()
    print(f"Restored: {restored}")
