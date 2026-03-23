"""
feedback_loop.py — Accuracy Feedback Loop
--------------------------------------------
Analyzes verified predictions (correct and incorrect) to learn
which signal patterns are reliable and which produce false positives.

The loop:
1. Fetch all verified predictions from the database
2. Analyze which keywords, authors, and dimensions appeared in each
3. Compute success rates per keyword, per author, per pattern
4. Generate weight adjustments for the classifier
5. Store learned weights in Supabase for persistence

The classifier can then apply these adjustments to sharpen future scoring.

Usage:
    from feedback_loop import feedback_engine

    # Run the learning cycle
    feedback_engine.learn()

    # Get weight adjustments for the classifier
    adjustments = feedback_engine.get_adjustments()

    # Get a human-readable learning report
    report = feedback_engine.get_learning_report()
"""

import os
import json
from datetime import datetime, timedelta
from collections import defaultdict
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger

logger = get_logger(__name__)

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ============================================
# SQL — Run in Supabase if table doesn't exist
# ============================================

SETUP_SQL = """
CREATE TABLE IF NOT EXISTS learned_weights (
    id BIGSERIAL PRIMARY KEY,
    weight_key TEXT UNIQUE NOT NULL,
    category TEXT NOT NULL,
    original_weight DECIMAL DEFAULT 0,
    learned_adjustment DECIMAL DEFAULT 0,
    effective_weight DECIMAL DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    success_rate DECIMAL DEFAULT 0,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
"""


class FeedbackEngine:
    """Learns from prediction accuracy to improve classifier weights."""

    def __init__(self):
        self._adjustments = {}
        self._report = {}
        self._last_learn = None

    def learn(self):
        """
        Run the full learning cycle:
        1. Fetch verified predictions
        2. Re-classify each predicted tweet to extract dimensions
        3. Track which patterns led to correct vs incorrect predictions
        4. Compute adjustments
        5. Save to database
        """
        logger.info("Feedback loop: starting learning cycle...")

        try:
            # Fetch all predictions with outcomes
            correct = self._fetch_predictions(was_correct=True)
            incorrect = self._fetch_predictions(was_correct=False)

            if not correct and not incorrect:
                logger.info("Feedback loop: no verified predictions to learn from yet")
                self._last_learn = datetime.now()
                return

            logger.info(f"Feedback loop: {len(correct)} correct, {len(incorrect)} incorrect predictions")

            # Analyze signal details to extract patterns
            keyword_stats = defaultdict(lambda: {"correct": 0, "incorrect": 0})
            author_stats = defaultdict(lambda: {"correct": 0, "incorrect": 0})
            score_range_stats = defaultdict(lambda: {"correct": 0, "incorrect": 0})
            signal_type_stats = defaultdict(lambda: {"correct": 0, "incorrect": 0})

            # Process correct predictions
            for pred in correct:
                self._extract_patterns(pred, keyword_stats, author_stats, score_range_stats, signal_type_stats, outcome="correct")

            # Process incorrect predictions
            for pred in incorrect:
                self._extract_patterns(pred, keyword_stats, author_stats, score_range_stats, signal_type_stats, outcome="incorrect")

            # Compute adjustments
            adjustments = {}

            # Keyword adjustments
            for keyword, stats in keyword_stats.items():
                total = stats["correct"] + stats["incorrect"]
                if total >= 2:  # Need minimum sample size
                    success_rate = stats["correct"] / total
                    # Boost keywords with >70% success, penalize below 30%
                    if success_rate >= 0.7:
                        adj = round((success_rate - 0.5) * 10, 1)  # +2 to +5
                    elif success_rate <= 0.3:
                        adj = round((success_rate - 0.5) * 10, 1)  # -2 to -5
                    else:
                        adj = 0
                    adjustments[f"keyword:{keyword}"] = {
                        "category": "keyword",
                        "adjustment": adj,
                        "success_rate": round(success_rate * 100, 1),
                        "correct": stats["correct"],
                        "incorrect": stats["incorrect"],
                    }

            # Author adjustments
            for author, stats in author_stats.items():
                total = stats["correct"] + stats["incorrect"]
                if total >= 2:
                    success_rate = stats["correct"] / total
                    if success_rate >= 0.7:
                        adj = round((success_rate - 0.5) * 15, 1)  # +3 to +7.5
                    elif success_rate <= 0.3:
                        adj = round((success_rate - 0.5) * 15, 1)  # -3 to -7.5
                    else:
                        adj = 0
                    adjustments[f"author:{author}"] = {
                        "category": "author",
                        "adjustment": adj,
                        "success_rate": round(success_rate * 100, 1),
                        "correct": stats["correct"],
                        "incorrect": stats["incorrect"],
                    }

            # Score range analysis (which score bands are most accurate)
            score_analysis = {}
            for score_range, stats in score_range_stats.items():
                total = stats["correct"] + stats["incorrect"]
                if total > 0:
                    success_rate = stats["correct"] / total
                    score_analysis[score_range] = {
                        "success_rate": round(success_rate * 100, 1),
                        "correct": stats["correct"],
                        "incorrect": stats["incorrect"],
                        "total": total,
                    }

            # Signal type analysis
            type_analysis = {}
            for stype, stats in signal_type_stats.items():
                total = stats["correct"] + stats["incorrect"]
                if total > 0:
                    success_rate = stats["correct"] / total
                    type_analysis[stype] = {
                        "success_rate": round(success_rate * 100, 1),
                        "correct": stats["correct"],
                        "incorrect": stats["incorrect"],
                    }

            # Store results
            self._adjustments = adjustments
            self._report = {
                "total_correct": len(correct),
                "total_incorrect": len(incorrect),
                "total_analyzed": len(correct) + len(incorrect),
                "keyword_adjustments": {k: v for k, v in adjustments.items() if v["category"] == "keyword"},
                "author_adjustments": {k: v for k, v in adjustments.items() if v["category"] == "author"},
                "score_range_analysis": score_analysis,
                "signal_type_analysis": type_analysis,
                "learned_at": datetime.now().isoformat(),
            }

            # Save to Supabase
            self._save_to_db(adjustments)

            self._last_learn = datetime.now()

            # Log summary
            boosted = [k for k, v in adjustments.items() if v["adjustment"] > 0]
            penalized = [k for k, v in adjustments.items() if v["adjustment"] < 0]
            logger.info(f"Feedback loop: {len(adjustments)} adjustments computed")
            if boosted:
                logger.info(f"  Boosted ({len(boosted)}): {', '.join(boosted[:5])}")
            if penalized:
                logger.info(f"  Penalized ({len(penalized)}): {', '.join(penalized[:5])}")

        except Exception as e:
            logger.error(f"Feedback loop failed: {e}", exc_info=True)

    def _fetch_predictions(self, was_correct):
        """Fetch predictions with a specific outcome."""
        try:
            result = (
                supabase.table("predictions")
                .select("*")
                .eq("was_correct", was_correct)
                .order("predicted_at", desc=True)
                .limit(200)
                .execute()
            )
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Failed to fetch predictions (correct={was_correct}): {e}")
            return []

    def _extract_patterns(self, prediction, keyword_stats, author_stats, score_range_stats, signal_type_stats, outcome):
        """Extract which patterns appeared in a prediction."""
        details = (prediction.get("signal_details", "") or "").lower()
        score = prediction.get("signal_score", 0)
        signal_type = prediction.get("signal_type", "unknown")
        company = prediction.get("company", "")
        ticker = prediction.get("ticker", "")

        # Extract keywords from signal_details
        from classifier import (
            SAYLOR_CODED, PURCHASE_DIRECT, ACCUMULATION_INTENT,
            CONVICTION, TRACKER_PATTERNS
        )

        all_keywords = {}
        all_keywords.update(SAYLOR_CODED)
        all_keywords.update(PURCHASE_DIRECT)
        all_keywords.update(ACCUMULATION_INTENT)
        all_keywords.update(CONVICTION)
        all_keywords.update(TRACKER_PATTERNS)

        for keyword in all_keywords:
            if keyword in details:
                keyword_stats[keyword][outcome] += 1

        # Track author from prediction details or company mapping
        # Try to extract author from signal_details
        if "@saylor" in details or "saylor" in details:
            author_stats["saylor"][outcome] += 1
        if "@phongle" in details or "phongle" in details:
            author_stats["phongle_"][outcome] += 1
        if "metaplanet" in details or "gerovich" in details:
            author_stats["metaplanet_jp"][outcome] += 1
        if "marathon" in details or "mara" in details.split():
            author_stats["marathondh"][outcome] += 1

        # Score range buckets
        if score >= 80:
            score_range_stats["80-100"][outcome] += 1
        elif score >= 60:
            score_range_stats["60-79"][outcome] += 1
        elif score >= 40:
            score_range_stats["40-59"][outcome] += 1
        else:
            score_range_stats["0-39"][outcome] += 1

        # Signal type
        signal_type_stats[signal_type][outcome] += 1

    def _save_to_db(self, adjustments):
        """Save learned weights to Supabase."""
        try:
            for key, data in adjustments.items():
                row = {
                    "weight_key": key,
                    "category": data["category"],
                    "learned_adjustment": data["adjustment"],
                    "success_count": data["correct"],
                    "failure_count": data["incorrect"],
                    "success_rate": data["success_rate"],
                    "last_updated": datetime.now().isoformat(),
                }
                supabase.table("learned_weights").upsert(row, on_conflict="weight_key").execute()

            logger.info(f"Saved {len(adjustments)} learned weights to DB")
        except Exception as e:
            logger.warning(f"Could not save learned weights to DB: {e}")

    def load_from_db(self):
        """Load previously learned weights from Supabase."""
        try:
            result = supabase.table("learned_weights").select("*").execute()
            if result.data:
                self._adjustments = {}
                for row in result.data:
                    self._adjustments[row["weight_key"]] = {
                        "category": row["category"],
                        "adjustment": float(row.get("learned_adjustment", 0)),
                        "success_rate": float(row.get("success_rate", 0)),
                        "correct": row.get("success_count", 0),
                        "incorrect": row.get("failure_count", 0),
                    }
                logger.info(f"Loaded {len(self._adjustments)} learned weights from DB")
            return self._adjustments
        except Exception as e:
            logger.debug(f"Could not load learned weights: {e}")
            return {}

    def get_adjustments(self):
        """Get all current weight adjustments."""
        return self._adjustments

    def get_keyword_adjustment(self, keyword):
        """Get the learned adjustment for a specific keyword."""
        key = f"keyword:{keyword}"
        if key in self._adjustments:
            return self._adjustments[key]["adjustment"]
        return 0

    def get_author_adjustment(self, author):
        """Get the learned adjustment for a specific author."""
        key = f"author:{author}"
        if key in self._adjustments:
            return self._adjustments[key]["adjustment"]
        return 0

    def get_learning_report(self):
        """Get a human-readable report of what the system has learned."""
        if not self._report and not self._adjustments:
            return "No learning data available. Run feedback_engine.learn() after predictions are verified."

        report = self._report or {}
        lines = [
            "📚 FEEDBACK LOOP — LEARNING REPORT",
            f"Analyzed: {report.get('total_analyzed', 0)} verified predictions "
            f"({report.get('total_correct', 0)} correct, {report.get('total_incorrect', 0)} incorrect)",
            "",
        ]

        # Keyword insights
        kw_adj = report.get("keyword_adjustments", {})
        if kw_adj:
            boosted = [(k.replace("keyword:", ""), v) for k, v in kw_adj.items() if v["adjustment"] > 0]
            penalized = [(k.replace("keyword:", ""), v) for k, v in kw_adj.items() if v["adjustment"] < 0]

            if boosted:
                lines.append("✅ Reliable Keywords (boosted):")
                for kw, data in sorted(boosted, key=lambda x: -x[1]["success_rate"])[:8]:
                    lines.append(f"   '{kw}': {data['success_rate']}% success ({data['correct']}/{data['correct']+data['incorrect']}) → +{data['adjustment']} boost")
                lines.append("")

            if penalized:
                lines.append("⚠️ Unreliable Keywords (penalized):")
                for kw, data in sorted(penalized, key=lambda x: x[1]["success_rate"])[:8]:
                    lines.append(f"   '{kw}': {data['success_rate']}% success ({data['correct']}/{data['correct']+data['incorrect']}) → {data['adjustment']} penalty")
                lines.append("")

        # Author insights
        auth_adj = report.get("author_adjustments", {})
        if auth_adj:
            lines.append("👤 Author Reliability:")
            for k, v in sorted(auth_adj.items(), key=lambda x: -x[1]["success_rate"]):
                author = k.replace("author:", "")
                emoji = "✅" if v["adjustment"] >= 0 else "⚠️"
                lines.append(f"   {emoji} @{author}: {v['success_rate']}% → {v['adjustment']:+.1f} adjustment")
            lines.append("")

        # Score range insights
        score_analysis = report.get("score_range_analysis", {})
        if score_analysis:
            lines.append("📊 Accuracy by Score Range:")
            for range_name in ["80-100", "60-79", "40-59", "0-39"]:
                if range_name in score_analysis:
                    data = score_analysis[range_name]
                    lines.append(f"   Score {range_name}: {data['success_rate']}% accurate ({data['correct']}/{data['total']})")
            lines.append("")

        # Signal type insights
        type_analysis = report.get("signal_type_analysis", {})
        if type_analysis:
            lines.append("📡 Accuracy by Signal Type:")
            for stype, data in type_analysis.items():
                lines.append(f"   {stype}: {data['success_rate']}% ({data['correct']}/{data['correct']+data['incorrect']})")

        if report.get("learned_at"):
            lines.append(f"\nLast learned: {report['learned_at'][:19]}")

        return "\n".join(lines)

    def format_for_email_html(self):
        """Format learning insights as HTML for the email briefing."""
        if not self._adjustments:
            return ""

        # Only show if we have meaningful data
        boosted = [(k, v) for k, v in self._adjustments.items() if v["adjustment"] > 0 and v["category"] == "keyword"]
        penalized = [(k, v) for k, v in self._adjustments.items() if v["adjustment"] < 0 and v["category"] == "keyword"]

        if not boosted and not penalized:
            return ""

        rows = ""
        for key, data in sorted(boosted, key=lambda x: -x[1]["success_rate"])[:3]:
            kw = key.replace("keyword:", "")
            rows += f'<span style="background: rgba(16,185,129,0.1); color: #10B981; padding: 2px 8px; border-radius: 4px; font-size: 10px; margin: 2px; display: inline-block;">✅ "{kw}" {data["success_rate"]}%</span>'

        for key, data in sorted(penalized, key=lambda x: x[1]["success_rate"])[:3]:
            kw = key.replace("keyword:", "")
            rows += f'<span style="background: rgba(239,68,68,0.1); color: #EF4444; padding: 2px 8px; border-radius: 4px; font-size: 10px; margin: 2px; display: inline-block;">⚠️ "{kw}" {data["success_rate"]}%</span>'

        return f"""
            <tr><td style="padding: 4px 36px 8px 36px;">
                <span style="color: #6b7280; font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em;">🧠 AI Learning — Keyword Reliability</span>
                <br>{rows}
            </td></tr>
        """


# ============================================
# GLOBAL INSTANCE
# ============================================
feedback_engine = FeedbackEngine()


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    logger.info("Feedback Loop — testing...")
    print(f"\n{'='*60}")
    print("  ACCURACY FEEDBACK LOOP — TEST")
    print(f"{'='*60}\n")

    feedback_engine.learn()
    print(feedback_engine.get_learning_report())

    logger.info("Feedback Loop test complete")
