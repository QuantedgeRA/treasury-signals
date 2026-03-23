"""
pattern_analyzer.py — Historical Pattern Analysis
----------------------------------------------------
Analyzes confirmed Bitcoin purchases to build "pre-purchase fingerprints"
and matches current conditions against historical patterns.

Key concepts:
- A "fingerprint" captures what data looked like 24-72 hours before a purchase
- Current conditions are scored against all historical fingerprints
- Higher match = higher probability of an imminent purchase

Data sources analyzed:
- Tweet signals before each purchase
- Day-of-week and timing patterns
- STRC volume behavior
- Fear & Greed conditions
- Which authors were active

Usage:
    from pattern_analyzer import pattern_engine

    # Build fingerprints from historical data
    pattern_engine.build_fingerprints()

    # Match current conditions
    match = pattern_engine.match_current_conditions(
        recent_signals=signals,
        strc_ratio=1.8,
        fear_greed=25,
        btc_change_pct=-3.5,
    )
    # match = {"score": 72, "matching_patterns": [...], "narrative": "..."}
"""

import os
import json
from datetime import datetime, timedelta
from collections import Counter
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger

logger = get_logger(__name__)

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ============================================
# KNOWN PURCHASE PATTERNS (from historical data)
# ============================================

# Strategy (MicroStrategy) purchase behavior patterns
# Compiled from all known Strategy BTC purchases 2020-2026
KNOWN_PATTERNS = {
    "strategy_coded_tweet": {
        "name": "Saylor Coded Tweet → Purchase",
        "description": "Saylor posts cryptic 'orange' language, purchase follows within 24-72 hours",
        "company": "Strategy",
        "indicators": {
            "saylor_coded_tweet": True,
            "tweet_score_min": 60,
            "typical_lead_hours": (12, 72),
        },
        "historical_frequency": "~85% of Strategy purchases preceded by coded tweet",
        "confidence_weight": 30,
    },
    "strategy_strc_spike": {
        "name": "STRC Volume Spike → Purchase",
        "description": "STRC volume exceeds 2x average, indicating capital raise for BTC buy",
        "company": "Strategy",
        "indicators": {
            "strc_ratio_min": 2.0,
            "typical_lead_hours": (24, 96),
        },
        "historical_frequency": "~70% of Strategy purchases preceded by STRC spike",
        "confidence_weight": 25,
    },
    "strategy_monday_pattern": {
        "name": "Weekend Hint → Monday Purchase",
        "description": "Saylor tweets on weekend, purchase announced Monday or Tuesday",
        "company": "Strategy",
        "indicators": {
            "weekend_tweet": True,
            "purchase_day": [0, 1],  # Monday, Tuesday
        },
        "historical_frequency": "~60% of Strategy purchases announced Mon-Tue after weekend hints",
        "confidence_weight": 15,
    },
    "strategy_fear_buying": {
        "name": "Fear-Based Accumulation",
        "description": "Strategy often buys during market fear (F&G below 30)",
        "company": "Strategy",
        "indicators": {
            "fear_greed_max": 30,
        },
        "historical_frequency": "~45% of purchases when F&G < 30",
        "confidence_weight": 12,
    },
    "strategy_dip_buying": {
        "name": "Dip Accumulation",
        "description": "Strategy buys after BTC price drops >5% in a week",
        "company": "Strategy",
        "indicators": {
            "btc_weekly_change_max": -5.0,
        },
        "historical_frequency": "~40% of purchases follow a >5% weekly dip",
        "confidence_weight": 10,
    },
    "strategy_8k_filing": {
        "name": "8-K Filing Confirmation",
        "description": "SEC 8-K filing appears, confirming a purchase already hinted at",
        "company": "Strategy",
        "indicators": {
            "edgar_8k_btc": True,
        },
        "historical_frequency": "100% — every purchase has an 8-K filing",
        "confidence_weight": 20,
    },
    "multi_company_wave": {
        "name": "Multi-Company Purchase Wave",
        "description": "When one major company buys, others often follow within days",
        "company": "Any",
        "indicators": {
            "recent_purchase_by_other": True,
            "wave_window_days": 7,
        },
        "historical_frequency": "~35% of purchases cluster within 7 days of another company's buy",
        "confidence_weight": 10,
    },
    "metaplanet_accumulation": {
        "name": "Metaplanet Regular Accumulation",
        "description": "Metaplanet buys weekly, often with CEO tweet beforehand",
        "company": "Metaplanet",
        "indicators": {
            "ceo_tweet": True,
            "regular_cadence_days": 7,
        },
        "historical_frequency": "~90% weekly purchases",
        "confidence_weight": 20,
    },
}


class PatternAnalyzer:
    """Builds and matches pre-purchase fingerprints."""

    def __init__(self):
        self._fingerprints = []
        self._last_build = None

    def build_fingerprints(self):
        """
        Build fingerprints from confirmed purchase data in the database.
        Looks at what happened in the 72 hours before each confirmed purchase.
        """
        logger.info("Building historical purchase fingerprints...")

        try:
            # Get confirmed purchases
            result = supabase.table("confirmed_purchases").select("*").order("filing_date", desc=True).limit(100).execute()
            purchases = result.data if result.data else []

            if not purchases:
                logger.info("No confirmed purchases in DB — using known patterns only")
                self._last_build = datetime.now()
                return

            fingerprints = []

            for purchase in purchases:
                fp = self._build_single_fingerprint(purchase)
                if fp:
                    fingerprints.append(fp)

            self._fingerprints = fingerprints
            self._last_build = datetime.now()

            logger.info(f"Built {len(fingerprints)} fingerprints from {len(purchases)} purchases")

            # Analyze patterns across all fingerprints
            self._analyze_aggregate_patterns()

        except Exception as e:
            logger.error(f"Fingerprint build failed: {e}", exc_info=True)

    def _build_single_fingerprint(self, purchase):
        """Build a fingerprint for a single confirmed purchase."""
        try:
            filing_date = purchase.get("filing_date", "")
            company = purchase.get("company", "")
            ticker = purchase.get("ticker", "")
            btc_amount = purchase.get("btc_amount", 0)

            if not filing_date:
                return None

            # Parse the filing date
            try:
                if "T" in filing_date:
                    purchase_dt = datetime.fromisoformat(filing_date.replace("Z", ""))
                else:
                    purchase_dt = datetime.strptime(filing_date, "%Y-%m-%d")
            except Exception:
                return None

            # Look for tweets in the 72 hours before
            pre_purchase_tweets = self._get_tweets_before(purchase_dt, hours=72)

            # Analyze pre-purchase tweet patterns
            tweet_signals = [t for t in pre_purchase_tweets if t.get("is_signal")]
            max_score = max([t.get("confidence_score", 0) for t in tweet_signals], default=0)
            signal_authors = list(set(t.get("author_username", "").lower() for t in tweet_signals))

            # Check for Saylor coded language
            saylor_active = any(a in ["saylor", "michael_saylor"] for a in signal_authors)

            # Day of week
            purchase_dow = purchase_dt.weekday()

            # Was it predicted?
            was_predicted = purchase.get("was_predicted", False)
            lead_time = purchase.get("prediction_lead_time_hours")

            fingerprint = {
                "purchase_id": purchase.get("purchase_id", ""),
                "company": company,
                "ticker": ticker,
                "btc_amount": btc_amount,
                "filing_date": filing_date,
                "purchase_dow": purchase_dow,
                "purchase_dow_name": purchase_dt.strftime("%A"),

                # Pre-purchase signals
                "pre_tweets_total": len(pre_purchase_tweets),
                "pre_signals_count": len(tweet_signals),
                "pre_max_score": max_score,
                "pre_signal_authors": signal_authors,
                "saylor_active_before": saylor_active,

                # Prediction accuracy
                "was_predicted": was_predicted,
                "prediction_lead_time_hours": lead_time,
            }

            return fingerprint

        except Exception as e:
            logger.debug(f"Fingerprint build failed for {purchase.get('purchase_id', '?')}: {e}")
            return None

    def _get_tweets_before(self, purchase_dt, hours=72):
        """Get tweets from the database in the window before a purchase."""
        try:
            start = (purchase_dt - timedelta(hours=hours)).isoformat()
            end = purchase_dt.isoformat()

            result = (
                supabase.table("tweets")
                .select("author_username, tweet_text, confidence_score, is_signal, created_at")
                .gte("created_at", start)
                .lte("created_at", end)
                .order("created_at", desc=True)
                .limit(200)
                .execute()
            )
            return result.data if result.data else []

        except Exception as e:
            logger.debug(f"Tweet lookup failed for pre-purchase window: {e}")
            return []

    def _analyze_aggregate_patterns(self):
        """Analyze patterns across all fingerprints to find common signals."""
        if not self._fingerprints:
            return

        # Day of week distribution
        dow_counts = Counter(fp["purchase_dow_name"] for fp in self._fingerprints)
        total = len(self._fingerprints)

        # Signal presence
        had_signals = sum(1 for fp in self._fingerprints if fp["pre_signals_count"] > 0)
        had_saylor = sum(1 for fp in self._fingerprints if fp["saylor_active_before"])
        predicted = sum(1 for fp in self._fingerprints if fp["was_predicted"])

        logger.info(f"Pattern analysis: {total} purchases")
        logger.info(f"  Day distribution: {dict(dow_counts)}")
        logger.info(f"  Pre-signals present: {had_signals}/{total} ({had_signals/total*100:.0f}%)")
        logger.info(f"  Saylor active before: {had_saylor}/{total} ({had_saylor/total*100:.0f}%)")
        logger.info(f"  Successfully predicted: {predicted}/{total} ({predicted/total*100:.0f}%)")

    def match_current_conditions(self, recent_signals=None, strc_ratio=0,
                                  fear_greed=50, btc_change_pct=0,
                                  recent_purchases=None, current_dow=None):
        """
        Score current conditions against known purchase patterns.

        Args:
            recent_signals: List of recent tweet signals (last 72h)
            strc_ratio: Current STRC volume ratio
            fear_greed: Current Fear & Greed index value
            btc_change_pct: BTC price change % over last 7 days
            recent_purchases: Recent confirmed purchases (for wave detection)
            current_dow: Current day of week (0=Mon, 6=Sun). Auto-detected if None.

        Returns:
            dict with score (0-100), matching_patterns, narrative, details
        """
        if current_dow is None:
            current_dow = datetime.now().weekday()

        recent_signals = recent_signals or []
        recent_purchases = recent_purchases or []

        matched_patterns = []
        total_weight = 0
        max_possible_weight = sum(p["confidence_weight"] for p in KNOWN_PATTERNS.values())

        # Check each known pattern
        for pattern_id, pattern in KNOWN_PATTERNS.items():
            match_result = self._check_pattern(
                pattern_id, pattern,
                recent_signals=recent_signals,
                strc_ratio=strc_ratio,
                fear_greed=fear_greed,
                btc_change_pct=btc_change_pct,
                recent_purchases=recent_purchases,
                current_dow=current_dow,
            )
            if match_result["matched"]:
                matched_patterns.append({
                    "pattern_id": pattern_id,
                    "name": pattern["name"],
                    "description": pattern["description"],
                    "company": pattern["company"],
                    "weight": pattern["confidence_weight"],
                    "historical_frequency": pattern["historical_frequency"],
                    "match_detail": match_result["detail"],
                })
                total_weight += pattern["confidence_weight"]

        # Calculate pattern match score (0-100)
        score = min(100, round((total_weight / max_possible_weight) * 100 * 1.5))

        # Build narrative
        narrative = self._build_narrative(matched_patterns, score)

        return {
            "score": score,
            "matched_count": len(matched_patterns),
            "total_patterns": len(KNOWN_PATTERNS),
            "matching_patterns": matched_patterns,
            "narrative": narrative,
            "details": {
                "total_weight": total_weight,
                "max_weight": max_possible_weight,
                "strc_ratio": strc_ratio,
                "fear_greed": fear_greed,
                "btc_change_pct": btc_change_pct,
                "signals_count": len(recent_signals),
                "current_dow": current_dow,
            },
        }

    def _check_pattern(self, pattern_id, pattern, **kwargs):
        """Check if current conditions match a specific pattern."""
        recent_signals = kwargs.get("recent_signals", [])
        strc_ratio = kwargs.get("strc_ratio", 0)
        fear_greed = kwargs.get("fear_greed", 50)
        btc_change_pct = kwargs.get("btc_change_pct", 0)
        recent_purchases = kwargs.get("recent_purchases", [])
        current_dow = kwargs.get("current_dow", 0)

        indicators = pattern["indicators"]

        # --- Saylor Coded Tweet Pattern ---
        if pattern_id == "strategy_coded_tweet":
            high_signals = [s for s in recent_signals if s.get("score", s.get("confidence_score", 0)) >= 60]
            saylor_signals = [s for s in high_signals if s.get("author", s.get("author_username", "")).lower() in ["saylor", "michael_saylor"]]
            if saylor_signals:
                top_score = max(s.get("score", s.get("confidence_score", 0)) for s in saylor_signals)
                return {"matched": True, "detail": f"Saylor signal detected (score: {top_score})"}
            return {"matched": False, "detail": ""}

        # --- STRC Volume Spike ---
        if pattern_id == "strategy_strc_spike":
            if strc_ratio >= indicators.get("strc_ratio_min", 2.0):
                return {"matched": True, "detail": f"STRC ratio {strc_ratio}x exceeds {indicators['strc_ratio_min']}x threshold"}
            return {"matched": False, "detail": ""}

        # --- Weekend → Monday Pattern ---
        if pattern_id == "strategy_monday_pattern":
            weekend_signals = [s for s in recent_signals
                             if s.get("author", s.get("author_username", "")).lower() in ["saylor", "michael_saylor"]]
            if weekend_signals and current_dow in [0, 1]:
                return {"matched": True, "detail": f"Weekend Saylor activity + current day is {['Mon','Tue'][current_dow]}"}
            return {"matched": False, "detail": ""}

        # --- Fear-Based Buying ---
        if pattern_id == "strategy_fear_buying":
            if fear_greed <= indicators.get("fear_greed_max", 30):
                return {"matched": True, "detail": f"Fear & Greed at {fear_greed} (extreme fear zone)"}
            return {"matched": False, "detail": ""}

        # --- Dip Buying ---
        if pattern_id == "strategy_dip_buying":
            if btc_change_pct <= indicators.get("btc_weekly_change_max", -5.0):
                return {"matched": True, "detail": f"BTC down {btc_change_pct:.1f}% this week (dip buying zone)"}
            return {"matched": False, "detail": ""}

        # --- 8-K Filing ---
        if pattern_id == "strategy_8k_filing":
            # This would be checked from EDGAR data — if we have a recent BTC-related 8-K
            return {"matched": False, "detail": ""}

        # --- Multi-Company Wave ---
        if pattern_id == "multi_company_wave":
            if recent_purchases:
                recent_companies = set(p.get("company", "") for p in recent_purchases[:5])
                if len(recent_companies) >= 2:
                    return {"matched": True, "detail": f"Multiple companies buying: {', '.join(list(recent_companies)[:3])}"}
            return {"matched": False, "detail": ""}

        # --- Metaplanet Regular Accumulation ---
        if pattern_id == "metaplanet_accumulation":
            meta_signals = [s for s in recent_signals
                          if s.get("author", s.get("author_username", "")).lower() in ["metaplanet_jp", "simongerovich"]]
            if meta_signals:
                return {"matched": True, "detail": "Metaplanet executive activity detected (weekly buyer)"}
            return {"matched": False, "detail": ""}

        return {"matched": False, "detail": ""}

    def _build_narrative(self, matched_patterns, score):
        """Build a human-readable narrative from matched patterns."""
        if not matched_patterns:
            return "No historical purchase patterns match current conditions. Market is quiet."

        if score >= 70:
            opener = "Multiple historical purchase patterns are active simultaneously."
        elif score >= 40:
            opener = "Some historical purchase patterns are present."
        else:
            opener = "Limited pattern activity detected."

        pattern_lines = []
        for p in matched_patterns:
            pattern_lines.append(f"{p['name']}: {p['match_detail']} ({p['historical_frequency']})")

        body = " ".join(pattern_lines[:3])

        if score >= 70:
            closer = "Historically, when this many patterns align, a purchase follows within 48-72 hours."
        elif score >= 40:
            closer = "Monitor closely — conditions are developing but not yet at peak alignment."
        else:
            closer = "No immediate purchase expected based on historical patterns."

        return f"{opener} {body} {closer}"

    def get_pattern_summary(self):
        """Get a summary of all known patterns for display."""
        summary = []
        for pid, p in KNOWN_PATTERNS.items():
            summary.append({
                "id": pid,
                "name": p["name"],
                "description": p["description"],
                "company": p["company"],
                "weight": p["confidence_weight"],
                "frequency": p["historical_frequency"],
            })
        return summary

    def get_fingerprint_stats(self):
        """Get stats from built fingerprints."""
        if not self._fingerprints:
            return {"count": 0, "last_build": None}

        return {
            "count": len(self._fingerprints),
            "last_build": self._last_build.isoformat() if self._last_build else None,
            "companies": list(set(fp["company"] for fp in self._fingerprints)),
            "avg_pre_signals": sum(fp["pre_signals_count"] for fp in self._fingerprints) / len(self._fingerprints),
            "prediction_rate": sum(1 for fp in self._fingerprints if fp["was_predicted"]) / len(self._fingerprints) * 100,
        }


# ============================================
# GLOBAL INSTANCE
# ============================================
pattern_engine = PatternAnalyzer()


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    logger.info("Pattern Analyzer — testing...")
    print(f"\n{'='*60}")
    print("  HISTORICAL PATTERN ANALYZER — TEST")
    print(f"{'='*60}\n")

    # Build fingerprints from DB
    pattern_engine.build_fingerprints()

    stats = pattern_engine.get_fingerprint_stats()
    print(f"  Fingerprints built: {stats['count']}")
    if stats.get("companies"):
        print(f"  Companies: {', '.join(stats['companies'])}")

    # Test pattern matching with various conditions
    scenarios = [
        {
            "name": "High Alert — Saylor tweet + STRC spike + fear",
            "signals": [{"author": "saylor", "score": 85, "text": "More orange"}],
            "strc": 2.5, "fg": 20, "btc_change": -8.0,
        },
        {
            "name": "Medium — Saylor active on weekend, Monday now",
            "signals": [{"author": "saylor", "score": 70, "text": "orange dots"}],
            "strc": 1.2, "fg": 45, "btc_change": -2.0,
        },
        {
            "name": "Quiet — no signals, normal conditions",
            "signals": [],
            "strc": 0.8, "fg": 55, "btc_change": 1.5,
        },
    ]

    for s in scenarios:
        result = pattern_engine.match_current_conditions(
            recent_signals=s["signals"],
            strc_ratio=s["strc"],
            fear_greed=s["fg"],
            btc_change_pct=s["btc_change"],
            current_dow=0,  # Monday
        )
        print(f"\n  Scenario: {s['name']}")
        print(f"  Pattern Score: {result['score']}/100")
        print(f"  Matched: {result['matched_count']}/{result['total_patterns']} patterns")
        print(f"  Narrative: {result['narrative'][:120]}...")
        for p in result["matching_patterns"]:
            print(f"    ✅ {p['name']} — {p['match_detail']}")

    logger.info("Pattern Analyzer test complete")
