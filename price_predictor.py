"""
price_predictor.py — Signal-to-Price Correlation Engine
---------------------------------------------------------
Analyzes historical relationship between our signal scores
and subsequent BTC price movements.

Answers: "When our system scores 60+, what happens to BTC
price in the following 24, 48, and 72 hours?"

Stores results in Supabase for dashboard display.

Usage:
    from price_predictor import predictor

    # Run the analysis (once per day)
    predictor.analyze()

    # Get latest insights
    insights = predictor.get_insights()
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


# Score bands to analyze
SCORE_BANDS = [
    {"label": "80-100 (Very High)", "min": 80, "max": 100, "key": "very_high"},
    {"label": "60-79 (High)", "min": 60, "max": 79, "key": "high"},
    {"label": "40-59 (Moderate)", "min": 40, "max": 59, "key": "moderate"},
    {"label": "20-39 (Low)", "min": 20, "max": 39, "key": "low"},
    {"label": "0-19 (Minimal)", "min": 0, "max": 19, "key": "minimal"},
]

# Time windows to check
WINDOWS = [
    {"label": "24h", "hours": 24},
    {"label": "48h", "hours": 48},
    {"label": "72h", "hours": 72},
    {"label": "7d", "hours": 168},
]


class PricePredictor:
    """Correlates signal scores with BTC price movements."""

    def __init__(self):
        self._insights = None
        self._last_analysis = None

    def analyze(self):
        """
        Run the full correlation analysis:
        1. Fetch all predictions with timestamps
        2. Fetch BTC price history from leaderboard snapshots
        3. For each prediction, check what BTC did afterward
        4. Aggregate by score band
        5. Store results
        """
        logger.info("Price predictor: starting analysis...")

        try:
            # Get predictions
            result = supabase.table("predictions").select("*").order("predicted_at", desc=True).limit(500).execute()
            predictions = result.data if result.data else []

            if not predictions:
                logger.info("Price predictor: no predictions to analyze")
                return

            # Get BTC price snapshots
            snap_result = supabase.table("leaderboard_snapshots").select("snapshot_date, btc_price").order("snapshot_date", desc=True).limit(365).execute()
            snapshots = snap_result.data if snap_result.data else []

            if not snapshots:
                logger.info("Price predictor: no price snapshots available")
                return

            # Build price lookup by date
            price_by_date = {}
            for snap in snapshots:
                if snap.get("btc_price") and snap.get("snapshot_date"):
                    price_by_date[snap["snapshot_date"]] = float(snap["btc_price"])

            if not price_by_date:
                logger.info("Price predictor: no valid price data")
                return

            # Analyze each prediction
            band_results = defaultdict(lambda: {w["label"]: [] for w in WINDOWS})

            for pred in predictions:
                score = pred.get("signal_score", 0)
                pred_date_str = pred.get("predicted_at", "")

                if not pred_date_str:
                    continue

                # Parse prediction date
                try:
                    if "T" in pred_date_str:
                        pred_dt = datetime.fromisoformat(pred_date_str.replace("Z", "").replace("+00:00", ""))
                    else:
                        pred_dt = datetime.strptime(pred_date_str[:10], "%Y-%m-%d")
                except Exception:
                    continue

                pred_date = pred_dt.strftime("%Y-%m-%d")

                # Get price at prediction time
                price_at_pred = price_by_date.get(pred_date)
                if not price_at_pred:
                    # Try nearby dates
                    for offset in [1, -1, 2, -2]:
                        nearby = (pred_dt + timedelta(days=offset)).strftime("%Y-%m-%d")
                        if nearby in price_by_date:
                            price_at_pred = price_by_date[nearby]
                            break

                if not price_at_pred:
                    continue

                # Determine which band
                band_key = None
                for band in SCORE_BANDS:
                    if band["min"] <= score <= band["max"]:
                        band_key = band["key"]
                        break

                if not band_key:
                    continue

                # Check price at each future window
                for window in WINDOWS:
                    future_dt = pred_dt + timedelta(hours=window["hours"])
                    future_date = future_dt.strftime("%Y-%m-%d")

                    future_price = price_by_date.get(future_date)
                    if not future_price:
                        for offset in [1, -1, 2, -2]:
                            nearby = (future_dt + timedelta(days=offset)).strftime("%Y-%m-%d")
                            if nearby in price_by_date:
                                future_price = price_by_date[nearby]
                                break

                    if future_price:
                        pct_change = ((future_price - price_at_pred) / price_at_pred) * 100
                        band_results[band_key][window["label"]].append(pct_change)

            # Calculate averages per band per window
            insights = {
                "generated_at": datetime.now().isoformat(),
                "total_predictions_analyzed": len(predictions),
                "price_snapshots_available": len(price_by_date),
                "bands": {},
            }

            for band in SCORE_BANDS:
                key = band["key"]
                band_data = band_results[key]
                band_insight = {
                    "label": band["label"],
                    "min_score": band["min"],
                    "max_score": band["max"],
                    "windows": {},
                }

                for window in WINDOWS:
                    wl = window["label"]
                    changes = band_data[wl]
                    if changes:
                        avg = sum(changes) / len(changes)
                        positive = sum(1 for c in changes if c > 0)
                        band_insight["windows"][wl] = {
                            "avg_change_pct": round(avg, 2),
                            "median_change_pct": round(sorted(changes)[len(changes) // 2], 2),
                            "positive_rate": round((positive / len(changes)) * 100, 1),
                            "sample_size": len(changes),
                            "min_change": round(min(changes), 2),
                            "max_change": round(max(changes), 2),
                        }
                    else:
                        band_insight["windows"][wl] = {
                            "avg_change_pct": 0,
                            "positive_rate": 0,
                            "sample_size": 0,
                        }

                insights["bands"][key] = band_insight

            # Generate headline insight
            high_band = insights["bands"].get("high", {}).get("windows", {}).get("72h", {})
            very_high_band = insights["bands"].get("very_high", {}).get("windows", {}).get("72h", {})

            headline = ""
            if very_high_band.get("sample_size", 0) >= 3:
                headline = f"When our system scores 80+, BTC moves an average of {very_high_band['avg_change_pct']:+.1f}% in the following 72 hours ({very_high_band['positive_rate']}% positive, n={very_high_band['sample_size']})."
            elif high_band.get("sample_size", 0) >= 3:
                headline = f"When our system scores 60+, BTC moves an average of {high_band['avg_change_pct']:+.1f}% in the following 72 hours ({high_band['positive_rate']}% positive, n={high_band['sample_size']})."
            else:
                headline = f"Analyzing {len(predictions)} predictions against {len(price_by_date)} price snapshots. More data needed for high-confidence correlations."

            insights["headline"] = headline

            # Save to Supabase
            self._save_insights(insights)
            self._insights = insights
            self._last_analysis = datetime.now()

            logger.info(f"Price predictor: analyzed {len(predictions)} predictions across {len(price_by_date)} price points")
            logger.info(f"Price predictor: {headline}")

        except Exception as e:
            logger.error(f"Price predictor failed: {e}", exc_info=True)

    def _save_insights(self, insights):
        """Save insights to Supabase."""
        try:
            supabase.table("price_predictions").upsert({
                "prediction_date": datetime.now().strftime("%Y-%m-%d"),
                "insights_json": json.dumps(insights),
                "headline": insights.get("headline", ""),
                "generated_at": datetime.now().isoformat(),
            }, on_conflict="prediction_date").execute()
            logger.debug("Price prediction insights saved to DB")
        except Exception as e:
            logger.warning(f"Could not save price prediction insights: {e}")

    def get_insights(self):
        """Get latest insights from Supabase."""
        if self._insights:
            return self._insights

        try:
            result = supabase.table("price_predictions").select("*").order("generated_at", desc=True).limit(1).execute()
            if result.data and result.data[0].get("insights_json"):
                self._insights = json.loads(result.data[0]["insights_json"])
                return self._insights
        except Exception as e:
            logger.debug(f"Could not load price prediction insights: {e}")

        return None


# ============================================
# GLOBAL INSTANCE
# ============================================
predictor = PricePredictor()


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    logger.info("Price Predictor — running analysis...")
    predictor.analyze()
    insights = predictor.get_insights()
    if insights:
        print(f"\n{'='*60}")
        print("  PRICE PREDICTION MODEL")
        print(f"{'='*60}\n")
        print(f"Headline: {insights.get('headline', '')}")
        print(f"Predictions analyzed: {insights.get('total_predictions_analyzed', 0)}")
        print(f"Price snapshots: {insights.get('price_snapshots_available', 0)}")
        for key, band in insights.get("bands", {}).items():
            print(f"\n  {band['label']}:")
            for wl, data in band.get("windows", {}).items():
                if data.get("sample_size", 0) > 0:
                    print(f"    {wl}: avg {data['avg_change_pct']:+.2f}% | {data['positive_rate']}% positive | n={data['sample_size']}")
    logger.info("Price Predictor test complete")
