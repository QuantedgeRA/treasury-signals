"""
purchase_keys.py — the canonical natural key for purchase/sale rows.

A purchase/sale event is uniquely identified by:

    (normalize_ticker(ticker), filing_date, btc_amount)

This is the SINGLE SOURCE OF TRUTH for that definition on the Python side.
It must stay in lockstep with two other copies:

  1. migrations/0022_purchase_dedup_constraints.sql — the DB UNIQUE index
     `public.dedup_normalize_ticker()` + ux_confirmed_purchases_natural /
     ux_confirmed_sales_natural. That index is the HARD guarantee; this
     module is the app-side mirror used to pre-check and to recognise the
     unique-violation when it fires.
  2. purchase_reconciler._normalize_ticker_for_dedup() — the reconciler's
     long-standing copy of the same suffix list.

If you change SUFFIXES here, change all three together. The suffix list
intentionally does NOT include ".T" — Japanese tickers like 3825.T keep
their suffix (3825.T and 3825 are different entities to us).

WHY btc_amount is in the key: companies legitimately buy more than once on
the same day (El Salvador's "buying the dip" second buy; MARA split
tranches). Those differ by amount, so they stay distinct. A true duplicate
is the same event copied by two ingest paths — same ticker, date AND amount.
"""
from __future__ import annotations

# Exchange suffixes stripped during normalization (verbatim from
# purchase_reconciler._normalize_ticker_for_dedup — keep in sync).
SUFFIXES = (
    ".US", ".L", ".TO", ".AX", ".DE", ".PA", ".SW", ".HK", ".KS", ".SS",
    ".SZ", ".SA", ".V", ".ST", ".CO", ".MI", ".BR", ".MC", ".OL", ".HE", ".IS",
)


def normalize_ticker(ticker: str) -> str:
    """Uppercase, trim, and strip ONE known exchange suffix.

    Mirrors the SQL dedup_normalize_ticker() in migration 0022 exactly.
    """
    if not ticker:
        return ""
    t = ticker.upper().strip()
    for suffix in SUFFIXES:
        if t.endswith(suffix):
            return t[: -len(suffix)]
    return t


def natural_key(ticker: str, filing_date, btc_amount) -> tuple:
    """The canonical dedup key for a purchase/sale row.

    filing_date is compared by its YYYY-MM-DD prefix; btc_amount as float so
    4871 and 4871.0 compare equal (matching the numeric DB index semantics).
    """
    try:
        amt = float(btc_amount or 0)
    except (TypeError, ValueError):
        amt = 0.0
    return (normalize_ticker(ticker), str(filing_date or "")[:10], amt)


def is_duplicate_key_error(err) -> bool:
    """True if a Supabase/Postgres error is a unique-constraint violation.

    Lets direct writers treat a natural-key collision as a benign skip
    ("already recorded by another source") instead of a hard failure.
    """
    s = str(err).lower()
    return (
        "23505" in s
        or "duplicate key" in s
        or "unique constraint" in s
        or "already exists" in s
    )
