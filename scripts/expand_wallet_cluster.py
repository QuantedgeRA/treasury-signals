"""
One-shot: expand the wallet cluster from a seed address using Tier 2
heuristics (common-input + change-address).

Calls treasury_signals.pipelines.wallet_clusterer.expand_from_seed()
with --apply support and writes results to entity_wallets +
wallet_clusters.

Usage:
    python scripts/expand_wallet_cluster.py SEED_ADDRESS TICKER             # dry-run
    python scripts/expand_wallet_cluster.py SEED_ADDRESS TICKER --apply     # write

Example:
    python scripts/expand_wallet_cluster.py bc1q.... MSTR --apply

The seed_address must already exist in entity_wallets at confidence >= 70.
If you're seeding a new entity for the first time, manually INSERT the
seed into entity_wallets first (with attribution_method='community_known'
or 'public_disclosure' depending on your source), THEN run this script.

OUTPUT
======
On success, prints stats:
    {seed, hops_walked, derived_count, by_heuristic, by_hop, dry_run}

Derived addresses are inserted into entity_wallets with:
    attribution_method = 'cluster_expansion' or 'change_addr'
    source_citation    = the evidence tx URL
    confidence_score   = base score minus hop-distance decay
    notes              = "Derived via X from seed Y at hop N"

PERFORMANCE
===========
blockchain.com API is the bottleneck (~3 req/sec sustained). For a seed
with ~10 transactions, expect ~2 minutes. For a seed with hundreds of
transactions, can be 10-30 minutes. The clusterer caps at 3 hops and
5000 derived addresses for safety.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
if not (SUPABASE_URL and SUPABASE_KEY):
    sys.exit("SUPABASE_URL + SUPABASE_KEY required in .env")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

from treasury_signals.pipelines.wallet_clusterer import expand_from_seed


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    seed = sys.argv[1].strip()
    ticker = sys.argv[2].strip().upper()
    apply = "--apply" in sys.argv

    # Validate the seed exists in entity_wallets at sufficient confidence
    try:
        res = (
            supabase.table("entity_wallets")
            .select("ticker, entity_name, confidence_score, attribution_method")
            .eq("wallet_address", seed)
            .limit(1)
            .execute()
        )
    except Exception as e:
        sys.exit(f"DB error checking seed: {e}")

    if not res.data:
        sys.exit(
            f"Seed address {seed} NOT in entity_wallets. Per the strict "
            f"methodology, you must add a seed manually first (with a "
            f"primary-source or community-known attribution) before "
            f"running cluster expansion."
        )

    seed_row = res.data[0]
    if seed_row["ticker"] != ticker:
        sys.exit(
            f"Seed ticker mismatch: entity_wallets has {seed_row['ticker']}, "
            f"you passed {ticker}. Aborting to avoid cross-attribution."
        )
    if (seed_row.get("confidence_score") or 0) < 70:
        sys.exit(
            f"Seed confidence is {seed_row['confidence_score']}, below the "
            f"70 floor for cluster expansion. Higher-confidence seed required."
        )

    entity_name = seed_row.get("entity_name") or ticker

    print(f"Seed:      {seed}")
    print(f"Ticker:    {ticker}")
    print(f"Entity:    {entity_name}")
    print(f"Seed conf: {seed_row['confidence_score']} via {seed_row['attribution_method']}")
    print(f"Mode:      {'APPLYING' if apply else 'DRY-RUN'}")
    print("=" * 70)

    stats = expand_from_seed(
        seed_address=seed,
        ticker=ticker,
        entity_name=entity_name,
        dry_run=not apply,
    )
    print()
    print("Stats:")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    if not apply:
        print()
        print("Re-run with --apply to write derived attributions to entity_wallets + wallet_clusters.")


if __name__ == "__main__":
    main()
