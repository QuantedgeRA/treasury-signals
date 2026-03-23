"""
database.py
-----------
Handles all database operations with Supabase.
This file has ONE job: store and retrieve tweets.
"""

import os
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger
from freshness_tracker import freshness

logger = get_logger(__name__)

# Load credentials from .env file
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Connect to Supabase
try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info("Supabase connection initialized")
except Exception as e:
    logger.critical(f"Failed to initialize Supabase client: {e}", exc_info=True)
    raise


def tweet_exists(tweet_id):
    """Check if we've already stored this tweet."""
    try:
        result = supabase.table("tweets").select("tweet_id").eq("tweet_id", tweet_id).execute()
        return len(result.data) > 0
    except Exception as e:
        logger.error(f"DB check failed for tweet {tweet_id}: {e}", exc_info=True)
        return False


def save_tweet(info, company=""):
    """
    Save a tweet to the database.
    Returns True if saved (new tweet), False if skipped (duplicate).
    """
    # Skip if we already have it
    if tweet_exists(info["tweet_id"]):
        return False

    try:
        row = {
            "tweet_id": info["tweet_id"],
            "author_username": info["author"],
            "company": company,
            "tweet_text": info["text"],
            "tweet_url": info.get("url", ""),
            "created_at": info["created_at"],
            "like_count": info.get("like_count", 0),
            "retweet_count": info.get("retweet_count", 0),
            "view_count": info.get("view_count", 0),
            "is_reply": info.get("is_reply", False),
            "is_signal": False,
            "confidence_score": 0,
            "processed": False,
        }
        supabase.table("tweets").insert(row).execute()
        return True
    except Exception as e:
        logger.error(f"Failed to save tweet {info.get('tweet_id', 'unknown')}: {e}", exc_info=True)
        return False


def get_new_tweets():
    """Get all tweets that haven't been processed yet."""
    try:
        result = (
            supabase.table("tweets")
            .select("*")
            .eq("processed", False)
            .order("inserted_at", desc=True)
            .execute()
        )
        freshness.record_success("supabase", detail=f"Fetched {len(result.data)} unprocessed tweets")
        return result.data
    except Exception as e:
        logger.error(f"Failed to fetch unprocessed tweets: {e}", exc_info=True)
        freshness.record_failure("supabase", error=str(e))
        return []


def mark_processed(tweet_id, is_signal=False, confidence_score=0):
    """Mark a tweet as processed and optionally flag it as a signal."""
    try:
        supabase.table("tweets").update({
            "processed": True,
            "is_signal": is_signal,
            "confidence_score": confidence_score,
        }).eq("tweet_id", tweet_id).execute()
    except Exception as e:
        logger.error(f"Failed to mark tweet {tweet_id} as processed: {e}", exc_info=True)


# ============================================
# QUICK TEST - Run this file directly to test
# ============================================
if __name__ == "__main__":
    logger.info("Testing Supabase connection...")

    if not SUPABASE_URL or "your-project" in SUPABASE_URL:
        logger.error("Set your SUPABASE_URL in the .env file")
        exit()

    if not SUPABASE_KEY or "paste" in SUPABASE_KEY:
        logger.error("Set your SUPABASE_KEY in the .env file")
        exit()

    logger.info(f"URL: {SUPABASE_URL}")
    logger.info(f"Key: {SUPABASE_KEY[:20]}...")

    # Test saving a dummy tweet
    test_tweet = {
        "tweet_id": "test_123",
        "text": "This is a test tweet",
        "author": "test_user",
        "created_at": "Sun Mar 15 12:00:00 +0000 2026",
        "like_count": 0,
        "retweet_count": 0,
        "view_count": 0,
        "url": "",
        "is_reply": False,
    }

    logger.info("Saving test tweet...")
    saved = save_tweet(test_tweet, company="Test Company")
    if saved:
        logger.info("Tweet saved to database")
    else:
        logger.info("Tweet already exists (or error occurred)")

    logger.info("Checking if tweet exists...")
    exists = tweet_exists("test_123")
    logger.info(f"Tweet exists: {exists}")

    logger.info("Fetching unprocessed tweets...")
    new_tweets = get_new_tweets()
    logger.info(f"Found {len(new_tweets)} unprocessed tweets")

    # Clean up test data
    try:
        supabase.table("tweets").delete().eq("tweet_id", "test_123").execute()
        logger.info("Test data cleaned up")
    except Exception as e:
        logger.warning(f"Could not clean up test data: {e}")

    logger.info("Database connection is working!")
