"""
direction_classifier.py — classify the *direction* of a BTC treasury 8-K.

The same 8-K mentioning a Bitcoin purchase can be bullish or bearish for the
stock depending on HOW the company is funding it. From the documented 2025
reactions:

    Pure buy (cash on hand)   → GameStop initial pop +11.7%
    Raise-then-buy (dilutive) → GameStop follow-on raise -22.5%
                                Metaplanet Q4 -8%
    Convertible / structured  → Mixed; depends on terms
    Sale / divestment         → Bearish (BTC outflow)

Knowing the event happened isn't enough for a trader — knowing the *direction*
is. This module produces a direction label + confidence so:

  1. Alert templates can render direction prominently ('PURE BUY · +avg 9%').
  2. /proof page can aggregate by direction.
  3. Future correlation engine work can weight signal by direction.

Design: keyword classifier first. The 8-K boilerplate is highly stereotyped —
ATM offerings, registered directs, convertible notes all have characteristic
phrasings that regex can catch with high precision. Claude escalation for
ambiguous cases is a planned follow-up; not in scope here.

False-positive control: we require BOTH a capital-raise marker AND a BTC
keyword. A raise-only 8-K without BTC mention isn't a treasury event at all
and should never have reached this classifier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class DirectionResult:
    """Structured output from classify_direction."""

    direction: str       # 'pure_buy' | 'raise_then_buy' | 'convertible' | 'sale' | 'unclear'
    confidence: int      # 0-100
    reasoning: str       # short human-readable explanation
    raise_terms: list    # raise-related terms matched
    sale_terms: list     # sale-related terms matched


# ─── Pattern banks ────────────────────────────────────────────────────────
# Capital-raise markers — order roughly by specificity (more specific = higher
# weight). Boundaries (\b) protect against substring false positives.

_ATM_TERMS = [
    r"\bat[- ]the[- ]market\b",
    r"\bATM offering\b",
    r"\bATM facility\b",
    r"\bequity distribution agreement\b",
]
_REGISTERED_DIRECT_TERMS = [
    r"\bregistered direct\b",
    r"\bregistered offering\b",
    r"\bfollow[- ]on offering\b",
    r"\bpublic offering of (?:common )?stock\b",
]
_CONVERTIBLE_TERMS = [
    r"\bconvertible (?:senior )?notes?\b",
    r"\bconvertible debentures?\b",
    r"\bcapped call\b",
]
_DEBT_TERMS = [
    r"\bsenior secured notes?\b",
    r"\bterm loan\b",
    r"\bcredit facility\b",
    r"\brevolving credit\b",
]
_GENERIC_RAISE_TERMS = [
    r"\bproceeds from the offering\b",
    r"\bunderwriting agreement\b",
    r"\bprivate placement\b",
    r"\bnet proceeds\b",
    r"\bshares (?:to be )?issued\b",
    r"\bnewly issued shares\b",
    r"\bdilution\b",
]

# Sale / divestment markers
_SALE_TERMS = [
    r"\bsold\b.{0,50}\b(?:bitcoin|btc)\b",
    r"\bdisposed of\b.{0,50}\b(?:bitcoin|btc)\b",
    r"\bdivested\b",
    r"\bliquidated\b.{0,50}\b(?:bitcoin|btc)\b",
    r"\breduced its (?:bitcoin|btc) (?:holdings|position)\b",
    r"\bsale of\b.{0,30}\b(?:bitcoin|btc)\b",
]

# BTC keyword — required to gate the classifier; a raise 8-K without BTC isn't
# a treasury event.
_BTC_KEYWORDS = re.compile(r"\b(?:bitcoin|btc|digital asset(?:s)? (?:treasury|reserve))\b", re.IGNORECASE)


def _find_matches(text_lower: str, patterns: list) -> list:
    """Return the unique pattern strings that matched, deduped & sorted."""
    hits = set()
    for p in patterns:
        if re.search(p, text_lower):
            hits.add(p.strip(r"\b").replace(r"\s+", " "))
    return sorted(hits)


# ─── Public API ───────────────────────────────────────────────────────────


def classify_direction(filing_text: str) -> DirectionResult:
    """Classify the direction of a BTC treasury filing.

    Returns DirectionResult with direction in:
        'pure_buy'       — BTC purchase from existing cash/operations
        'raise_then_buy' — BTC purchase funded by ATM/follow-on/registered direct
        'convertible'    — BTC purchase funded by convertible notes / structured debt
        'sale'           — BTC divestment
        'unclear'        — filing matches no direction pattern (rare)

    Cheap (regex-only). Safe to call on every classified filing.
    """
    if not filing_text:
        return DirectionResult("unclear", 0, "empty input", [], [])

    if not _BTC_KEYWORDS.search(filing_text):
        return DirectionResult(
            "unclear", 0,
            "no BTC/Bitcoin keyword in filing — not a treasury event",
            [], [],
        )

    t = filing_text.lower()

    # ── Sale first (cleanest signal; usually unambiguous) ───────────────
    sale_hits = _find_matches(t, _SALE_TERMS)
    if sale_hits:
        # Even strong sale phrasing can co-occur with a partial purchase ("sold
        # 500 BTC and acquired 1,000 BTC"), so check for net-purchase phrasing
        # before locking in 'sale'.
        net_purchase_hint = re.search(
            r"\b(?:net (?:purchase|acquisition)|increased its (?:bitcoin|btc) holdings|added to its (?:bitcoin|btc))\b",
            t,
        )
        if not net_purchase_hint:
            return DirectionResult(
                "sale", 80,
                f"Sale phrasing matched: {sale_hits[0]}",
                [], sale_hits,
            )

    # ── Capital-raise markers ───────────────────────────────────────────
    convertible_hits = _find_matches(t, _CONVERTIBLE_TERMS)
    atm_hits = _find_matches(t, _ATM_TERMS)
    registered_hits = _find_matches(t, _REGISTERED_DIRECT_TERMS)
    debt_hits = _find_matches(t, _DEBT_TERMS)
    generic_hits = _find_matches(t, _GENERIC_RAISE_TERMS)

    all_raise_hits = convertible_hits + atm_hits + registered_hits + debt_hits + generic_hits

    if convertible_hits:
        # Convertibles are a distinct flavor — neither bullish-pure-buy nor
        # straight-dilutive raise. Market reactions are conditional on terms.
        return DirectionResult(
            "convertible", 75,
            f"Convertible/structured-debt phrasing: {convertible_hits[0]}",
            all_raise_hits, [],
        )

    if atm_hits or registered_hits:
        # The clearest dilutive signal — ATM or follow-on with BTC purchase.
        marker = (atm_hits + registered_hits)[0]
        confidence = 85 if (atm_hits and registered_hits) else 80
        return DirectionResult(
            "raise_then_buy", confidence,
            f"Dilutive raise marker: {marker}",
            all_raise_hits, [],
        )

    if debt_hits or len(generic_hits) >= 2:
        # Weaker raise signal — could be refi rather than new dilution.
        marker = (debt_hits + generic_hits)[0]
        return DirectionResult(
            "raise_then_buy", 65,
            f"Raise-adjacent phrasing: {marker} (lower confidence)",
            all_raise_hits, [],
        )

    # ── Pure buy: BTC present, no raise markers ─────────────────────────
    return DirectionResult(
        "pure_buy", 75,
        "BTC purchase phrasing without capital-raise markers",
        [], [],
    )


# ─── Smoke test ───────────────────────────────────────────────────────────


if __name__ == "__main__":
    samples = [
        (
            "Pure buy",
            "On March 25, 2025, the Company acquired approximately 12,345 Bitcoin for an "
            "aggregate purchase price of $1.2 billion using cash on hand. Total holdings "
            "are now 528,185 BTC.",
        ),
        (
            "ATM raise",
            "On June 11, 2025, the Company announced the establishment of an at-the-market "
            "offering program of up to $750 million of common stock. Net proceeds will be used "
            "in part to acquire additional Bitcoin for the Company's treasury reserve.",
        ),
        (
            "Convertible note raise",
            "The Company priced $800 million of 0% convertible senior notes due 2030 to be used "
            "for the acquisition of additional Bitcoin.",
        ),
        (
            "Registered direct + BTC",
            "The Company entered into a securities purchase agreement for a registered direct "
            "offering of common stock with net proceeds to be deployed into Bitcoin holdings.",
        ),
        (
            "Sale",
            "The Company sold 1,500 BTC to fund operating expenses; total Bitcoin holdings now "
            "stand at 38,500 BTC.",
        ),
        (
            "Unclear (no BTC)",
            "The Company completed an at-the-market offering of $200 million in common stock to "
            "fund general corporate purposes.",
        ),
    ]
    for name, text in samples:
        r = classify_direction(text)
        print(f"{name:<25} direction={r.direction:<16} conf={r.confidence:<3} reason={r.reasoning}")
