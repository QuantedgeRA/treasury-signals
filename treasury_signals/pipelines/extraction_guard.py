"""
extraction_guard.py — sanity bounds for extracted BTC transaction amounts
=========================================================================
A regex- or AI-extracted transaction amount can be catastrophically wrong: a
holdings TOTAL parsed as a single trade, a "100,000 BTC target" parsed as a
purchase, a decimal/locale misread inflating by 1000x. On the customer alert
path a single wrong number — "MSTR SOLD 843,738 BTC" — is a churned subscriber.

This module is the LAST GATE before an extracted number reaches a paying
customer (Telegram alert) or the confirmed_purchases/sales ledger. The 3x
holdings check used to live only in the enrichment path (filing_parser), which
runs minutes later — far too late to stop the real-time alert. This guard runs
on the sub-60s path, so it must be pure and fast: the caller supplies
current_holdings (our best-known number for the entity), and these functions do
no I/O.

Verdicts:
  ok=True   → safe to alert / persist
  ok=False  → suppress the customer alert AND skip the ledger write; the filing
              is still stored (as a holdings/no-transaction record) for forensics
              and the reason is logged + sent to Sentry for admin review.

Bias: when in doubt SUPPRESS. A missed alert on a genuine mega-purchase is
recoverable (the enrichment path + next sync still capture it); a wrong number
blasted to every paying customer is not.
"""
from dataclasses import dataclass

# Total BTC that will ever exist (~21M). Any single "transaction" at or above
# this is definitionally a parse error (a market cap, a satoshi count, etc.).
MAX_BTC_SUPPLY = 21_000_000

# No single corporate or sovereign BTC transaction in history approaches this.
# MicroStrategy's largest single purchase was ~tens of thousands of BTC. A lone
# filing reporting a six-figure-plus "transaction" is almost always a holdings
# total or a multi-year accumulation target misparsed as one trade. Set
# generously so a genuinely large new-entrant buy (e.g. a 30k-BTC debut) passes.
IMPLAUSIBLE_SINGLE_TXN = 200_000

# A sale cannot exceed holdings. Allow a small tolerance because our holdings
# number may lag the filing by a sync cycle (the filing itself is the freshest
# source). Beyond this multiple the "sale" is a holdings-total misparse.
SALE_HOLDINGS_TOLERANCE = 1.05

# A purchase that is a large multiple of current holdings is almost always a
# target/goal ("aims to hold 100,000 BTC") or the holdings total, not one buy.
# Mirrors the long-standing 3x check from filing_parser, now on the alert path.
PURCHASE_HOLDINGS_MULTIPLE = 3.0


@dataclass
class GuardVerdict:
    ok: bool       # True = safe to alert customers / write the ledger
    reason: str    # human-readable explanation (logs / admin Sentry)
    code: str      # machine tag: 'ok' | 'no_amount' | 'exceeds_supply'
    #                | 'implausible_txn' | 'sale_exceeds_holdings'
    #                | 'purchase_exceeds_holdings'

    def __bool__(self) -> bool:  # so callers can write `if not guard:`
        return self.ok


def _coerce(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (ValueError, TypeError):
        return 0.0


def validate_transaction(event_type, btc_amount, current_holdings=None) -> GuardVerdict:
    """Gate an extracted transaction amount before it reaches a customer.

    Args:
        event_type: 'purchase' | 'sale' | anything else (relative checks only
            apply to purchase/sale).
        btc_amount: the extracted TRANSACTION delta (bought/sold), NOT holdings.
        current_holdings: our best-known holdings for the entity, or None/0 if
            unknown. Relative (holdings-based) checks are skipped when unknown;
            absolute bounds still apply.

    Returns a GuardVerdict; falsy means SUPPRESS.
    """
    amt = _coerce(btc_amount)
    if amt <= 0:
        # No transaction number to alert on — not an error, just nothing to gate.
        return GuardVerdict(True, "no transaction amount", "no_amount")

    # ── Absolute bounds — apply even when holdings are unknown ──
    if amt >= MAX_BTC_SUPPLY:
        return GuardVerdict(
            False,
            f"{amt:,.0f} BTC >= total supply ({MAX_BTC_SUPPLY:,}) — parse error",
            "exceeds_supply",
        )
    if amt >= IMPLAUSIBLE_SINGLE_TXN:
        return GuardVerdict(
            False,
            f"{amt:,.0f} BTC exceeds the plausible single-transaction ceiling "
            f"({IMPLAUSIBLE_SINGLE_TXN:,}) — likely a holdings total or target",
            "implausible_txn",
        )

    # ── Relative bounds — need a known holdings figure ──
    holdings = _coerce(current_holdings)
    if holdings > 0:
        et = (event_type or "").lower()
        if et == "sale" and amt > holdings * SALE_HOLDINGS_TOLERANCE:
            return GuardVerdict(
                False,
                f"sale of {amt:,.0f} BTC exceeds known holdings ({holdings:,.0f}) "
                f"— almost certainly a holdings-total misparse, not a real sale",
                "sale_exceeds_holdings",
            )
        if et == "purchase" and amt > holdings * PURCHASE_HOLDINGS_MULTIPLE:
            return GuardVerdict(
                False,
                f"purchase of {amt:,.0f} BTC exceeds {PURCHASE_HOLDINGS_MULTIPLE:g}x "
                f"current holdings ({holdings:,.0f}) — likely a target/goal or "
                f"holdings total, not a single buy",
                "purchase_exceeds_holdings",
            )

    return GuardVerdict(True, "within sane bounds", "ok")
