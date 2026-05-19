"""
exec_signal_detector.py — pattern detectors for CEO-led pre-announcement signals.

Some executives (Saylor most famously, with a 107/107 historical hit rate on
MSTR purchase pre-announcements) tweet recognizable patterns 5-7 days before
the formal 8-K lands. The generic tweet classifier in `pipelines/classifier.py`
scores those tweets the same as any other bullish post, which under-weights
the strongest leading indicators in the entire market.

This module adds named pattern detectors per priority=high account from
accounts.json. Each detector returns a structured result that the tweet
processing pipeline can use to override the classifier's score and tag the
signal with the named pattern, so:

    1. High-conviction CEO patterns reliably cross the 60 alert threshold
       without needing multi-stream correlation.
    2. The dashboard/alert templates can name the pattern explicitly
       ("Saylor tracker") rather than the generic "high-impact signal".
    3. Backtests can measure each pattern's actual hit rate separately.

Design notes:
    - Text-only for v1. The existing tweet pipeline doesn't capture media
      attachments; adding image OCR is a separate slice. Most CEO patterns
      have characteristic text anyway (Saylor: "Strategy", BTC count;
      Mallers: "Twenty One", "acquired"; Tahil: "Metaplanet", "purchased").
    - Detectors are ordered by confidence — first match wins. A tweet from
      @saylor matching the tracker pattern won't also try the generic
      "purchase keyword" pattern.
    - Confidence scores reflect HISTORICAL hit rate, not a probability
      estimate. Saylor at 85 reflects 107/107; others lower until backtested.
    - Designed to be cheap (regex + string contains). No LLM calls in v1.
      Escalation to Claude for ambiguous cases is a future slice.

Integration: see `helpers.process_and_alert()`. The detector runs after the
generic classifier; if it fires, the tweet signal's score is replaced with
`max(classifier_score, detector_confidence)` and the pattern name is included
in the correlation engine's components JSONB.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


# ─── Pattern definitions ───────────────────────────────────────────────────


@dataclass
class ExecSignal:
    """Structured result from a detector."""

    fired: bool
    pattern: str = ""              # e.g. "saylor_tracker"
    confidence: int = 0            # 0-100; replaces classifier score when fired
    reasoning: str = ""            # short human-readable explanation


# ─── Pattern context — for alert templates ────────────────────────────────
# Maps pattern name → marketing-grade narrative shown in pre-announcement
# alerts. The historical/lead numbers are CLAIMS until backtested against
# our own data; keep wording cautious. Imported by telegram_bot.send_alert.

PATTERN_CONTEXT = {
    "saylor_tracker": {
        "title": "SAYLOR TRACKER SIGNAL",
        "company": "Strategy (MSTR)",
        "historical": "Historically preceded MSTR purchase 8-Ks with 5-7 day lead time. (107/107 in external dataset; not yet validated against our own historical tweets.)",
        "expected_lead": "5-7 days",
    },
    "mallers_acquisition": {
        "title": "MALLERS ACQUISITION SIGNAL",
        "company": "Twenty One Capital (XXI)",
        "historical": "Twenty One Capital CEO posts often accompany or briefly precede 8-K filings.",
        "expected_lead": "Hours to 1 day",
    },
    "metaplanet_purchase": {
        "title": "METAPLANET PURCHASE SIGNAL",
        "company": "Metaplanet (3350.T)",
        "historical": "Metaplanet account posts have historically tracked closely with EDINET filings.",
        "expected_lead": "1-3 days",
    },
    "mara_production_update": {
        "title": "MARA PRODUCTION SIGNAL",
        "company": "MARA Holdings (MARA)",
        "historical": "MARA monthly production-update tweet typically precedes the official 8-K.",
        "expected_lead": "Hours to 1 day",
    },
}


# ─── Saylor — the canonical signal ────────────────────────────────────────
# Historical: 107/107 MSTR purchase announcements preceded by a tweet
# matching one of these patterns. Typical lead time 5-7 days.
#
# Patterns observed:
#   1. Tracker chart tweet: short caption + image of mstr-tracker / saylor's
#      tracker chart. Text often contains BTC count or "Strategy" and
#      sometimes the exact phrase "Bitcoin Tracker".
#   2. Direct accumulation note: "Strategy has acquired N BTC for $X"
#      (these are mostly retweets/replies confirming a buy that already
#      happened — exclude from "pre-announcement" pattern).
#   3. "I love Bitcoin / orange dot" tweets WITH a tracker image — usually
#      hours-to-days before a buy.
#
# v1: detect (1) via text keywords. Image presence not yet captured.

_SAYLOR_TRACKER_TERMS = [
    r"\btracker\b",
    r"\bchart\b",
    r"\bbitcoin tracker\b",
    r"\borange dot\b",
    r"\borange pill\b",
]
# Strong corroborators when combined with tracker terms (or any of these
# alone when from @saylor with a numeric BTC count).
_SAYLOR_CORROBORATORS = [
    r"\bstrategy\b",
    r"\bbtc\b",
    r"\bbitcoin\b",
    r"\$\d{1,3}(?:,\d{3})*(?:\.\d+)?(?:\s*(?:m|b|million|billion))?",
    r"\d{1,3}(?:,\d{3})+\s*(?:btc|bitcoin)",
]


def _detect_saylor(text: str) -> Optional[ExecSignal]:
    t = text.lower()
    tracker_hit = next((p for p in _SAYLOR_TRACKER_TERMS if re.search(p, t)), None)
    if not tracker_hit:
        return None

    corroborator_hits = [p for p in _SAYLOR_CORROBORATORS if re.search(p, t)]
    if not corroborator_hits:
        # Tracker keyword alone (e.g., "I love this chart") — too weak.
        return None

    # Tracker phrase + BTC/Strategy reference is the high-conviction shape.
    confidence = 85 if len(corroborator_hits) >= 2 else 75
    return ExecSignal(
        fired=True,
        pattern="saylor_tracker",
        confidence=confidence,
        reasoning=f"@saylor tweet matches tracker pattern (term={tracker_hit!r}, "
                  f"{len(corroborator_hits)} BTC/Strategy corroborator(s)). "
                  f"Historical: 107/107 MSTR pre-announcements, 5-7 day lead.",
    )


# ─── Mallers — Twenty One Capital ─────────────────────────────────────────
# Pattern: announcement-adjacent tweets often use "acquired", "added",
# "Twenty One" + BTC amount, sometimes with exchange or treasury phrasing.
# Lead time observed: hours to a day (faster news cadence than MSTR).

_MALLERS_TERMS = [
    r"\bacquired\b",
    r"\bbought\b",
    r"\badded\b",
    r"\bpurchas(ed|ing)\b",
    r"\baccumulat(ed|ing|ion)\b",
]


def _detect_mallers(text: str) -> Optional[ExecSignal]:
    t = text.lower()
    if not any(re.search(p, t) for p in _MALLERS_TERMS):
        return None
    if not re.search(r"\b(?:btc|bitcoin|twenty\s*one)\b", t):
        return None
    # Numeric BTC reference strongly boosts confidence.
    has_number = bool(re.search(r"\d{1,3}(?:[,\.]\d{3})*\s*(?:btc|bitcoin)?", t))
    confidence = 75 if has_number else 65
    return ExecSignal(
        fired=True,
        pattern="mallers_acquisition",
        confidence=confidence,
        reasoning=f"@jackmallers tweet matches Twenty One acquisition pattern "
                  f"(numeric={'yes' if has_number else 'no'}).",
    )


# ─── Metaplanet (Tahil & company account) ─────────────────────────────────
# Pattern: bilingual posts often referencing 'purchased' or 'increased
# holdings'. Numeric BTC count is a strong tell.

_METAPLANET_TERMS = [
    r"\bpurchas(ed|e|ing)\b",
    r"\bacquired\b",
    r"\bincreas(ed|ing)\b",
    r"\bholdings?\b",
]


def _detect_metaplanet(text: str) -> Optional[ExecSignal]:
    t = text.lower()
    if not any(re.search(p, t) for p in _METAPLANET_TERMS):
        return None
    if not re.search(r"\b(?:btc|bitcoin|metaplanet|3350)\b", t):
        return None
    has_number = bool(re.search(r"\d{1,3}(?:[,\.]\d{3})*\s*(?:btc|bitcoin)?", t))
    confidence = 75 if has_number else 60
    return ExecSignal(
        fired=True,
        pattern="metaplanet_purchase",
        confidence=confidence,
        reasoning=f"Metaplanet account tweet matches purchase pattern "
                  f"(numeric={'yes' if has_number else 'no'}).",
    )


# ─── MARA — official company account ──────────────────────────────────────
# Pattern: monthly mining update tweets ("April production update") with
# BTC count often precede the official 8-K by a few hours to a day.

_MARA_TERMS = [
    r"\bproduction\b",
    r"\bmonthly update\b",
    r"\bmined\b",
    r"\bholdings?\b",
]


def _detect_mara(text: str) -> Optional[ExecSignal]:
    t = text.lower()
    if not any(re.search(p, t) for p in _MARA_TERMS):
        return None
    if not re.search(r"\b(?:btc|bitcoin)\b", t):
        return None
    has_number = bool(re.search(r"\d{1,3}(?:[,\.]\d{3})*\s*(?:btc|bitcoin)?", t))
    confidence = 70 if has_number else 55
    return ExecSignal(
        fired=True,
        pattern="mara_production_update",
        confidence=confidence,
        reasoning=f"MARA tweet matches monthly production-update pattern "
                  f"(numeric={'yes' if has_number else 'no'}).",
    )


# ─── Dispatch table — username → detector ─────────────────────────────────
# Username matching is case-insensitive. Keep this in sync with
# accounts.json priority=high entries.

_DETECTORS = {
    "saylor": _detect_saylor,
    "jackmallers": _detect_mallers,
    "twentyone": _detect_mallers,
    "metaplanet_jp": _detect_metaplanet,
    "metaplanet_inc": _detect_metaplanet,
    "maraholdings": _detect_mara,
}


# ─── Public API ───────────────────────────────────────────────────────────


def detect_exec_signal(author_username: str, tweet_text: str) -> ExecSignal:
    """Run the pattern detector for the given author, if one is registered.

    Returns ExecSignal(fired=False, ...) for unknown authors or non-matching
    tweets. Cheap (regex only); safe to call on every classified tweet.
    """
    if not author_username or not tweet_text:
        return ExecSignal(fired=False)

    detector = _DETECTORS.get(author_username.lower().lstrip("@"))
    if not detector:
        return ExecSignal(fired=False)

    result = detector(tweet_text)
    return result or ExecSignal(fired=False)


# ─── Manual smoke test ────────────────────────────────────────────────────
# Run `python -m treasury_signals.pipelines.exec_signal_detector` to sanity-
# check the detectors against representative tweets.

if __name__ == "__main__":
    samples = [
        ("saylor", "The Bitcoin tracker continues to climb. Strategy holds 444,262 BTC."),
        ("saylor", "Just got back from Nashville."),
        ("jackmallers", "Twenty One just acquired 3,500 BTC. We are accumulating."),
        ("MARAHoldings", "April production update: mined 612 BTC, holdings now 51,234 BTC."),
        ("randomperson", "I love Bitcoin"),
    ]
    for user, text in samples:
        sig = detect_exec_signal(user, text)
        print(f"@{user:<14} fired={sig.fired:<5} pattern={sig.pattern:<25} "
              f"conf={sig.confidence:<3} — {text[:60]}")
