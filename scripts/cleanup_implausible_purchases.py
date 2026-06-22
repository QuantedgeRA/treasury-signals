"""
cleanup_implausible_purchases.py — purge impossible rows from the ledger.

Some confirmed_purchases / confirmed_sales rows were ingested BEFORE the
extraction_guard ran on every write path (it now runs centrally in
purchase_reconciler.reconcile_and_save). Those rows contain holdings TOTALS or
targets misparsed as single transactions — e.g. "Strategy purchased 1,076,589
BTC" (more than its entire treasury, and >5% of all BTC that will ever exist).
They poison the dashboard's monthly/all-time totals, the purchases page, timing
analysis, top-buyers, and competitive deltas.

This script replays the SAME guard (extraction_guard.validate_transaction) over
both ledgers and removes rows it rejects on ABSOLUTE bounds (>= 21M supply, or
>= 200k single-transaction ceiling). It deliberately does NOT apply the
relative holdings-multiple check here, because we don't have a reliable
per-entity holdings snapshot at cleanup time and don't want to delete a
borderline-but-real row — the absolute bounds alone catch every known-corrupt
row.

SAFETY: dry-run by DEFAULT. It prints exactly what it would delete. Pass --apply
to actually delete. After --apply, PROBE: re-run with no flag and confirm 0
rows flagged, and recompute the dashboard monthly total.

Usage:
    python scripts/cleanup_implausible_purchases.py            # dry-run (default)
    python scripts/cleanup_implausible_purchases.py --apply    # delete flagged rows
"""
import sys

from treasury_signals.pipelines.extraction_guard import validate_transaction

try:
    from treasury_signals.pipelines.purchase_reconciler import supabase
except Exception as e:  # pragma: no cover
    sys.exit(f"Could not init Supabase client: {e}")

# Only delete on absolute-bound rejections — never on the relative holdings
# check (which needs a holdings figure we don't have here).
ABSOLUTE_REJECT_CODES = {"exceeds_supply", "implausible_txn"}


def fetch_all(table, idcol):
    rows, start, page = [], 0, 1000
    while True:
        res = (
            supabase.table(table)
            .select(f"{idcol}, company, ticker, filing_date, btc_amount, usd_amount, price_per_btc, source")
            .range(start, start + page - 1)
            .execute()
        )
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < page:
            break
        start += page
    return rows


def scan(table, idcol, event_type, apply):
    rows = fetch_all(table, idcol)
    flagged = []
    for r in rows:
        verdict = validate_transaction(event_type, r.get("btc_amount"))
        if not verdict and verdict.code in ABSOLUTE_REJECT_CODES:
            flagged.append((r, verdict))

    print(f"\n=== {table}: {len(rows)} rows scanned, {len(flagged)} implausible ===")
    for r, v in flagged:
        print(
            f"  {r.get(idcol)}  {r.get('company')} ({r.get('ticker')})  "
            f"{float(r.get('btc_amount') or 0):,.0f} BTC  "
            f"${float(r.get('usd_amount') or 0):,.0f}  {r.get('filing_date')}  "
            f"-> {v.code}"
        )

    if not flagged:
        return 0

    if not apply:
        print(f"  [dry-run] would delete {len(flagged)} row(s) from {table}. Re-run with --apply.")
        return len(flagged)

    deleted = 0
    for r, _ in flagged:
        try:
            supabase.table(table).delete().eq(idcol, r.get(idcol)).execute()
            deleted += 1
        except Exception as e:
            print(f"  ! delete failed for {r.get(idcol)}: {e}")
    print(f"  DELETED {deleted}/{len(flagged)} row(s) from {table}.")
    return deleted


def main():
    apply = "--apply" in sys.argv
    mode = "APPLY (deleting)" if apply else "DRY-RUN (no writes)"
    print(f"cleanup_implausible_purchases — mode: {mode}")
    total = 0
    total += scan("confirmed_purchases", "purchase_id", "purchase", apply)
    total += scan("confirmed_sales", "sale_id", "sale", apply)
    print(f"\nTotal implausible rows {'deleted' if apply else 'flagged'}: {total}")
    if not apply and total:
        print("Run again with --apply to remove them, then probe (re-run dry, expect 0).")


if __name__ == "__main__":
    main()
