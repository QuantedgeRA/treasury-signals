"""
audit_purchase_dupes.py — READ-ONLY duplicate audit for confirmed_purchases
and confirmed_sales.

Replays the canonical natural key (pipelines/purchase_keys.natural_key:
normalized ticker + filing_date + btc_amount) across both tables and reports
any rows that share a key — i.e. the same event stored twice by different
ingest paths. This is exactly what migration 0022's unique index forbids;
run this if that index ever fails to create, or as a periodic integrity check.

No writes. SELECT only.

Usage:
    python scripts/audit_purchase_dupes.py
"""
import sys
from collections import defaultdict

from treasury_signals.pipelines.purchase_keys import natural_key

try:
    from treasury_signals.pipelines.purchase_reconciler import supabase
except Exception as e:  # pragma: no cover
    sys.exit(f"Could not init Supabase client: {e}")


def fetch_all(table, idcol):
    rows, start, page = [], 0, 1000
    while True:
        res = (
            supabase.table(table)
            .select(f"{idcol}, ticker, filing_date, btc_amount, source")
            .range(start, start + page - 1)
            .execute()
        )
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < page:
            break
        start += page
    return rows


def scan(table, idcol):
    rows = fetch_all(table, idcol)
    groups = defaultdict(list)
    for r in rows:
        groups[natural_key(r.get("ticker"), r.get("filing_date"), r.get("btc_amount"))].append(r)
    collisions = {k: v for k, v in groups.items() if len(v) > 1}
    print(f"\n=== {table}: {len(rows)} rows, {len(groups)} keys, {len(collisions)} COLLISIONS ===")
    for (nt, fd, amt), rs in sorted(collisions.items(), key=lambda x: str(x[0])):
        print(f"  ({nt!r}, {fd!r}, {amt:,.0f} BTC) -> {len(rs)} rows:")
        for r in rs:
            print(f"      {r.get(idcol)}  src={str(r.get('source',''))[:55]!r}")
    return len(collisions)


def main():
    c1 = scan("confirmed_purchases", "purchase_id")
    c2 = scan("confirmed_sales", "sale_id")
    print("\n" + "=" * 60)
    if c1 == 0 and c2 == 0:
        print("CLEAN — no natural-key duplicates.")
        return 0
    print(f"FOUND {c1} purchase + {c2} sale duplicate group(s). Resolve before/again.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
