"""
One-shot: strip the `.US` suffix from treasury_companies.ticker, with
auto-merge when both forms exist as duplicate rows.

Background (discovered 2026-05-21):
  BitcoinTreasuries.net uses Bloomberg-style tickers (`MARA.US`, `RIOT.US`,
  etc.). treasury_sync upserts them verbatim. The post-scan ticker_validator
  is supposed to clean them up, but the rename fails silently when a bare-
  form row already exists (UNIQUE constraint on ticker). Result: 60+
  duplicate rows where the `.US` form holds today's fresh data and the
  bare form is days/weeks stale.

This script fixes the immediate state. The persistent fix (so future syncs
do not recreate this state) is a follow-up patch to ticker_validator.

Strategy per `.US` row:
  RENAME — bare form not in treasury_companies. Plain UPDATE of the ticker.
  MERGE  — bare AND `.US` both exist:
            1. Pick the fresher row by last_updated.
            2. Copy a curated set of "live" columns (btc_holdings,
               shares_outstanding, etc.) from the fresher row into the
               bare row.
            3. Delete the `.US` row.
           If the fresher row IS the bare row, just delete the `.US` row.
  KEEP   — bare form not in SEC registry. This is a real foreign listing
           (TZUP.US, MOGO.US, etc.) — leave it alone.

Usage:
    python scripts/strip_us_ticker_suffix.py            # dry-run (default)
    python scripts/strip_us_ticker_suffix.py --apply    # actually write

REQUIRES A BACKUP. Run this first in Supabase SQL Editor:
    CREATE TABLE treasury_companies_backup_20260521 AS
    SELECT * FROM treasury_companies;

Requires SUPABASE_URL + SUPABASE_KEY in environment / .env.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

# Allow `from treasury_signals...` when invoked as `python scripts/...`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not (SUPABASE_URL and SUPABASE_KEY):
    sys.exit("SUPABASE_URL + SUPABASE_KEY required in .env")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
apply = "--apply" in sys.argv

print(f"Mode: {'APPLYING' if apply else 'DRY-RUN (pass --apply to write)'}")
print("-" * 70)

# Columns we treat as "live" — copied from the fresher row when merging.
# Identity columns (ticker, company, entity_type) are NOT merged; they
# stay on the bare row. created_at / id are immutable.
MERGE_COLUMNS = {
    "btc_holdings",
    "btc_holdings_recent",
    "shares_outstanding",
    "stock_price",
    "market_cap",
    "country",
    "category",
    "last_updated",
    "data_freshness",
    "source_url",
    "icon_url",
    "twitter_handle",
    "website",
    "purchase_history",
    "first_seen",
    "last_seen_in_source",
}


def _parse_dt(s):
    if not s:
        return datetime.min
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return datetime.min


# 1. Pull rows where ticker ends in `.US`
res = (
    supabase.table("treasury_companies")
    .select("*")
    .like("ticker", "%.US")
    .execute()
)
us_rows = res.data or []
print(f"Found {len(us_rows)} treasury_companies rows with `.US` suffix")
if not us_rows:
    sys.exit(0)

# 2. Load SEC ticker registry
from treasury_signals.sync.ticker_validator import _load_sec_tickers
sec_map = _load_sec_tickers() or {}
print(f"Loaded {len(sec_map)} entries from SEC company_tickers.json")

# 3. Index existing bare rows for collision lookup
bare_index: dict[str, dict] = {}
try:
    all_res = supabase.table("treasury_companies").select("*").execute()
    for r in (all_res.data or []):
        t = (r.get("ticker") or "").upper()
        if t and not t.endswith(".US"):
            bare_index[t] = r
except Exception as e:
    sys.exit(f"Could not fetch existing tickers for collision check: {e}")

# 4. Classify each .US row
to_rename: list[tuple[str, str, dict]] = []   # (us_ticker, bare, us_row)
to_merge:  list[tuple[str, str, dict, dict]] = []  # (us_ticker, bare, us_row, bare_row)
to_keep:   list[tuple[str, dict]] = []         # (us_ticker, us_row)

for us_row in us_rows:
    us_ticker = (us_row.get("ticker") or "").strip()
    if not us_ticker.endswith(".US"):
        continue
    bare = us_ticker[:-3].upper()
    if not bare:
        continue
    if bare not in sec_map:
        to_keep.append((us_ticker, us_row))
        continue
    if bare in bare_index:
        to_merge.append((us_ticker, bare, us_row, bare_index[bare]))
    else:
        to_rename.append((us_ticker, bare, us_row))

# 5. Report
print()
print(f"=== RENAME: {len(to_rename)} rows (no collision, plain UPDATE) ===")
for us, bare, row in to_rename:
    print(f"  {us:<12} -> {bare:<8}  {(row.get('company') or '')[:40]:<40}  {row.get('btc_holdings') or 0:>10,} BTC")

print()
print(f"=== MERGE: {len(to_merge)} duplicate pairs (pick fresher, delete other) ===")
for us, bare, us_row, bare_row in to_merge:
    us_dt = _parse_dt(us_row.get("last_updated"))
    bare_dt = _parse_dt(bare_row.get("last_updated"))
    if us_dt >= bare_dt:
        winner = "US"
        delta = (us_dt - bare_dt).days
    else:
        winner = "BARE"
        delta = (bare_dt - us_dt).days
    name = (us_row.get("company") or bare_row.get("company") or "")[:35]
    us_btc = us_row.get("btc_holdings") or 0
    bare_btc = bare_row.get("btc_holdings") or 0
    print(
        f"  {us:<12} + {bare:<8}  {name:<35}  winner={winner:<4} "
        f"(by {delta}d)  US={us_btc:>10,}  bare={bare_btc:>10,}"
    )

print()
print(f"=== KEEP: {len(to_keep)} rows (bare form not in SEC registry) ===")
for us, row in to_keep[:20]:
    print(f"  {us:<12}  {(row.get('company') or '')[:50]}")
if len(to_keep) > 20:
    print(f"  ...and {len(to_keep) - 20} more")

# 6. Apply
if not (to_rename or to_merge):
    print()
    print("No actions to apply.")
    sys.exit(0)

if not apply:
    print()
    print("Dry-run complete. Re-run with --apply to perform the actions above.")
    sys.exit(0)

print()
print("Applying...")

ok = 0
fail = 0

# Plain renames first — safe, no merges.
for us, bare, row in to_rename:
    try:
        supabase.table("treasury_companies").update({"ticker": bare}).eq("ticker", us).execute()
        print(f"  RENAME OK   {us} -> {bare}")
        ok += 1
    except Exception as e:
        print(f"  RENAME FAIL {us} -> {bare}: {e}")
        fail += 1

# Merges.
for us, bare, us_row, bare_row in to_merge:
    us_dt = _parse_dt(us_row.get("last_updated"))
    bare_dt = _parse_dt(bare_row.get("last_updated"))
    fresher = us_row if us_dt >= bare_dt else bare_row

    # Build the patch — only columns the fresher row has values for.
    patch = {}
    for col in MERGE_COLUMNS:
        if col not in fresher:
            continue
        val = fresher.get(col)
        # Allow null overrides only for last_updated / data_freshness;
        # otherwise prefer non-null values from the other row.
        if val is None:
            continue
        patch[col] = val

    try:
        # Step 1: update the bare row with the merged values.
        if patch:
            supabase.table("treasury_companies").update(patch).eq("ticker", bare).execute()
        # Step 2: delete the `.US` row (UNIQUE constraint is now free,
        # but we keep bare ticker as the canonical form, so we DELETE
        # rather than rename).
        supabase.table("treasury_companies").delete().eq("ticker", us).execute()
        print(f"  MERGE OK    {us} + {bare} -> {bare}   ({len(patch)} cols from fresher)")
        ok += 1
    except Exception as e:
        print(f"  MERGE FAIL  {us} + {bare}: {e}")
        fail += 1

print()
print(f"Done: {ok} actions OK, {fail} failed.")
if fail:
    sys.exit(1)
