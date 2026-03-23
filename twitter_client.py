"""
twitter_client.py
-----------------
Handles all communication with TwitterAPI.io
This file has ONE job: fetch tweets from X accounts.
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


def get_user_tweets(username):
    """
    Fetch the latest tweets from a specific X/Twitter user.
    """
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
