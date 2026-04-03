"""
twitter_client.py
-----------------
Handles all communication with TwitterAPI.io
This file has ONE job: fetch tweets from X accounts.

Includes a circuit breaker: if the API returns HTTP 402 (credits exhausted),
all subsequent calls are skipped instantly for the rest of that scan cycle.
The breaker resets at the start of each new scan via reset_circuit_breaker().
"""

import requests
import os
from dotenv import load_dotenv
from logger import get_logger
from freshness_tracker import freshness

logger = get_logger(__name__)

# Load API key from .env file
load_dotenv()
API_KEY = os.getenv("TWITTER_API_KEY")

# Base URL for TwitterAPI.io
BASE_URL = "https://api.twitterapi.io/twitter"

# Circuit breaker state
_circuit_open = False
_circuit_reason = ""
_circuit_tripped_at = None
_CIRCUIT_COOLDOWN_SECONDS = 300  # Auto-reset after 5 minutes (each scan is hours apart)


def reset_circuit_breaker():
    """Reset the circuit breaker. Called automatically after cooldown,
    or manually at the start of each scan from main.py."""
    global _circuit_open, _circuit_reason, _circuit_tripped_at
    _circuit_open = False
    _circuit_reason = ""
    _circuit_tripped_at = None


def get_user_tweets(username):
    """
    Fetch the latest tweets from a specific X/Twitter user.
    Returns immediately if circuit breaker is open (credits exhausted).
    """
    global _circuit_open, _circuit_reason, _circuit_tripped_at

    # Auto-reset circuit breaker after cooldown
    if _circuit_open and _circuit_tripped_at:
        import time
        elapsed = time.time() - _circuit_tripped_at
        if elapsed > _CIRCUIT_COOLDOWN_SECONDS:
            reset_circuit_breaker()

    # Circuit breaker: skip immediately if a previous call got 402
    if _circuit_open:
        return []

    url = f"{BASE_URL}/user/last_tweets"
    headers = {"X-API-Key": API_KEY}
    params = {"userName": username}

    try:
        response = requests.get(url, headers=headers, params=params)

        if response.status_code == 200:
            data = response.json()
            tweets = data.get("data", {}).get("tweets", [])
            if tweets is None:
                tweets = []
            freshness.record_success("twitter_api", detail=f"@{username}: {len(tweets)} tweets")
            return tweets
        elif response.status_code == 402:
            # Credits exhausted — trip the circuit breaker
            import time
            _circuit_open = True
            _circuit_reason = "Credits exhausted (HTTP 402)"
            _circuit_tripped_at = time.time()
            logger.warning(f"TwitterAPI credits exhausted (402 on @{username}) — skipping all remaining accounts this scan")
            freshness.record_failure("twitter_api", error="Credits exhausted (HTTP 402)")
            return []
        elif response.status_code == 429:
            logger.warning(f"TwitterAPI rate limited for @{username} — backing off")
            freshness.record_failure("twitter_api", error=f"Rate limited for @{username}")
            return []
        else:
            logger.error(
                f"TwitterAPI returned status {response.status_code} for @{username}: "
                f"{response.text[:200]}"
            )
            freshness.record_failure("twitter_api", error=f"HTTP {response.status_code} for @{username}")
            return []

    except requests.exceptions.Timeout:
        logger.error(f"TwitterAPI request timed out for @{username}")
        freshness.record_failure("twitter_api", error=f"Timeout for @{username}")
        return []
    except requests.exceptions.ConnectionError:
        logger.error(f"TwitterAPI connection failed for @{username}")
        freshness.record_failure("twitter_api", error=f"Connection failed for @{username}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error fetching tweets for @{username}: {e}", exc_info=True)
        freshness.record_failure("twitter_api", error=str(e))
        return []


def extract_tweet_info(tweet):
    """
    Pull out the important fields from a raw tweet object.
    """
    return {
        "tweet_id": tweet.get("id", "unknown"),
        "text": tweet.get("text", ""),
        "author": tweet.get("author", {}).get("userName", "") if isinstance(tweet.get("author"), dict) else "",
        "created_at": tweet.get("createdAt", ""),
        "retweet_count": tweet.get("retweetCount", 0),
        "like_count": tweet.get("likeCount", 0),
        "reply_count": tweet.get("replyCount", 0),
        "view_count": tweet.get("viewCount", 0),
        "url": tweet.get("url", ""),
        "is_reply": tweet.get("isReply", False),
    }


# ============================================
# QUICK TEST - Run this file directly to test
# ============================================
if __name__ == "__main__":
    logger.info("Testing TwitterAPI.io connection...")

    if not API_KEY or API_KEY == "your_twitterapi_io_key_here":
        logger.error("API key not set. Update TWITTER_API_KEY in .env")
        exit()

    logger.info(f"API Key loaded: {API_KEY[:8]}...{API_KEY[-4:]}")
    logger.info("Fetching tweets from @saylor...")

    tweets = get_user_tweets("saylor")

    if not tweets:
        logger.warning("No tweets returned. Check your API key and try again.")
    else:
        logger.info(f"Got {len(tweets)} tweets")

        for i, tweet in enumerate(tweets[:5]):
            info = extract_tweet_info(tweet)
            logger.info(
                f"Tweet #{i+1}: @{info['author']} — {info['text'][:80]}... "
                f"(Likes: {info['like_count']:,}, Views: {info['view_count']:,})"
            )

    logger.info("Twitter client test complete")
