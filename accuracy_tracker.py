"""
accuracy_tracker.py
-------------------
Tracks prediction accuracy by comparing our signals
against actual confirmed Bitcoin purchases.
"""

import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger

logger = get_logger(__name__)

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def setup_accuracy_tables():
    """
    Creates the predictions and confirmed_purchases tables.
    Run the following SQL in your Supabase SQL Editor:

    CREATE TABLE IF NOT EXISTS predictions (
        id BIGSERIAL PRIMARY KEY,
        prediction_id TEXT UNIQUE NOT NULL,
        company TEXT NOT NULL,
        ticker TEXT DEFAULT '',
        signal_type TEXT NOT NULL,
        signal_score INTEGER DEFAULT 0,
        signal_details TEXT DEFAULT '',
        predicted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        was_correct BOOLEAN DEFAULT NULL,
        matched_purchase_id TEXT DEFAULT NULL,
        notes TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS confirmed_purchases (
        id BIGSERIAL PRIMARY KEY,
        purchase_id TEXT UNIQUE NOT NULL,
        company TEXT NOT NULL,
        ticker TEXT DEFAULT '',
        btc_amount DECIMAL DEFAULT 0,
        usd_amount DECIMAL DEFAULT 0,
        price_per_btc DECIMAL DEFAULT 0,
        filing_date TEXT NOT NULL,
        filing_url TEXT DEFAULT '',
        was_predicted BOOLEAN DEFAULT FALSE,
        prediction_id TEXT DEFAULT NULL,
        prediction_lead_time_hours DECIMAL DEFAULT NULL,
        confirmed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );
    """
    logger.info("Run the SQL above in your Supabase SQL Editor to create the tables.")


def log_prediction(company, ticker, signal_type, signal_score, signal_details=""):
    """
    Log a new prediction when our system detects a signal.
    Called automatically when correlation score >= 50 or tweet score >= 60.
    """
    prediction_id = f"pred_{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    try:
        row = {
            "prediction_id": prediction_id,
            "company": company,
            "ticker": ticker,
            "signal_type": signal_type,
            "signal_score": signal_score,
            "signal_details": signal_details[:500],
        }
        supabase.table("predictions").insert(row).execute()
        logger.info(f"Prediction logged: {prediction_id} ({signal_type}, score: {signal_score})")
        return prediction_id
    except Exception as e:
        logger.error(f"Failed to log prediction {prediction_id}: {e}", exc_info=True)
        return None


def log_confirmed_purchase(company, ticker, btc_amount, usd_amount, price_per_btc, filing_date, filing_url=""):
    """
    Log a confirmed Bitcoin purchase from an 8-K filing.
    Then check if we predicted it.
    """
    purchase_id = f"buy_{ticker}_{filing_date}"

    try:
        existing = supabase.table("confirmed_purchases").select("purchase_id").eq("purchase_id", purchase_id).execute()
        if existing.data:
            logger.debug(f"Purchase already logged: {purchase_id}")
            return None

        prediction_match = find_matching_prediction(ticker, filing_date)

        row = {
            "purchase_id": purchase_id,
            "company": company,
            "ticker": ticker,
            "btc_amount": btc_amount,
            "usd_amount": usd_amount,
            "price_per_btc": price_per_btc,
            "filing_date": filing_date,
            "filing_url": filing_url,
            "was_predicted": prediction_match is not None,
            "prediction_id": prediction_match.get("prediction_id") if prediction_match else None,
            "prediction_lead_time_hours": prediction_match.get("lead_time_hours") if prediction_match else None,
        }

        supabase.table("confirmed_purchases").insert(row).execute()

        if prediction_match:
            supabase.table("predictions").update({
                "was_correct": True,
                "matched_purchase_id": purchase_id,
            }).eq("prediction_id", prediction_match["prediction_id"]).execute()

            logger.info(f"Purchase PREDICTED: {purchase_id} | Lead time: {prediction_match['lead_time_hours']:.1f}h")
        else:
            logger.info(f"Purchase NOT predicted: {purchase_id} (no matching signal in prior 72h)")

        return purchase_id
    except Exception as e:
        logger.error(f"Failed to log purchase {purchase_id}: {e}", exc_info=True)
        return None


def find_matching_prediction(ticker, filing_date):
    """
    Find a prediction that matches this purchase.
    A prediction "matches" if it was made within 72 hours before the filing.
    """
    try:
        try:
            purchase_date = datetime.strptime(filing_date, "%Y-%m-%d")
        except ValueError as e:
            logger.warning(f"Could not parse filing_date '{filing_date}': {e}")
            return None

        window_start = purchase_date - timedelta(hours=72)

        result = (
            supabase.table("predictions")
            .select("*")
            .eq("ticker", ticker)
            .gte("predicted_at", window_start.isoformat())
            .lte("predicted_at", purchase_date.isoformat())
            .order("signal_score", desc=True)
            .limit(1)
            .execute()
        )

        if result.data:
            prediction = result.data[0]
            pred_time = datetime.fromisoformat(prediction["predicted_at"].replace("Z", "+00:00")).replace(tzinfo=None)
            lead_time = (purchase_date - pred_time).total_seconds() / 3600

            return {
                "prediction_id": prediction["prediction_id"],
                "signal_score": prediction["signal_score"],
                "signal_type": prediction["signal_type"],
                "lead_time_hours": abs(lead_time),
            }

        return None
    except Exception as e:
        logger.error(f"Error finding prediction match for {ticker}/{filing_date}: {e}", exc_info=True)
        return None


def get_accuracy_stats():
    """Calculate overall accuracy statistics."""
    try:
        purchases = supabase.table("confirmed_purchases").select("*").order("filing_date", desc=True).execute()
        all_purchases = purchases.data if purchases.data else []

        predictions = supabase.table("predictions").select("*").order("predicted_at", desc=True).execute()
        all_predictions = predictions.data if predictions.data else []

        total_purchases = len(all_purchases)
        predicted_purchases = len([p for p in all_purchases if p.get("was_predicted")])
        unpredicted_purchases = total_purchases - predicted_purchases

        total_predictions = len(all_predictions)
        correct_predictions = len([p for p in all_predictions if p.get("was_correct") == True])
        incorrect_predictions = len([p for p in all_predictions if p.get("was_correct") == False])
        pending_predictions = len([p for p in all_predictions if p.get("was_correct") is None])

        purchase_hit_rate = (predicted_purchases / total_purchases * 100) if total_purchases > 0 else 0
        prediction_accuracy = (correct_predictions / (correct_predictions + incorrect_predictions) * 100) if (correct_predictions + incorrect_predictions) > 0 else 0

        lead_times = [p.get("prediction_lead_time_hours", 0) for p in all_purchases if p.get("was_predicted") and p.get("prediction_lead_time_hours")]
        avg_lead_time = sum(lead_times) / len(lead_times) if lead_times else 0

        return {
            "total_purchases": total_purchases,
            "predicted_purchases": predicted_purchases,
            "unpredicted_purchases": unpredicted_purchases,
            "purchase_hit_rate": round(purchase_hit_rate, 1),
            "total_predictions": total_predictions,
            "correct_predictions": correct_predictions,
            "incorrect_predictions": incorrect_predictions,
            "pending_predictions": pending_predictions,
            "prediction_accuracy": round(prediction_accuracy, 1),
            "avg_lead_time_hours": round(avg_lead_time, 1),
            "recent_purchases": all_purchases[:10],
            "recent_predictions": all_predictions[:10],
        }
    except Exception as e:
        logger.error(f"Failed to calculate accuracy stats: {e}", exc_info=True)
        return {
            "total_purchases": 0, "predicted_purchases": 0,
            "purchase_hit_rate": 0, "total_predictions": 0,
            "correct_predictions": 0, "prediction_accuracy": 0,
            "avg_lead_time_hours": 0,
        }


def format_accuracy_report(stats):
    """Format accuracy stats for display or Telegram."""

    return f"""
📊 ACCURACY REPORT — Treasury Signal Intelligence

🎯 Purchase Detection Rate:
  Confirmed purchases: {stats['total_purchases']}
  Predicted in advance: {stats['predicted_purchases']}
  Missed: {stats.get('unpredicted_purchases', 0)}
  Hit Rate: {stats['purchase_hit_rate']}%

📡 Signal Accuracy:
  Total predictions: {stats['total_predictions']}
  Confirmed correct: {stats['correct_predictions']}
  Confirmed wrong: {stats.get('incorrect_predictions', 0)}
  Pending verification: {stats.get('pending_predictions', 0)}
  Accuracy: {stats['prediction_accuracy']}%

⏱️ Average Lead Time: {stats['avg_lead_time_hours']} hours

---
Treasury Purchase Signal Intelligence
Multi-Signal Correlation Engine™
"""


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    logger.info("Accuracy Tracker — fetching stats...")
    stats = get_accuracy_stats()
    print(format_accuracy_report(stats))
    logger.info("Accuracy Tracker test complete")
