"""
twitter_client.py
-----------------
Handles all communication with TwitterAPI.io
This file has ONE job: fetch tweets from X accounts.
"""

import requests
import os
from dotenv import load_dotenv

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
            # Structure: { "data": { "tweets": [...] } }
            tweets = data.get("data", {}).get("tweets", [])
            if tweets is None:
                tweets = []
            return tweets
        else:
            print(f"  ERROR: API returned status {response.status_code} for @{username}")
            print(f"  Response: {response.text[:200]}")
            return []

    except Exception as e:
        print(f"  ERROR fetching tweets for @{username}: {e}")
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
    print("Testing TwitterAPI.io connection...\n")

    if not API_KEY or API_KEY == "your_twitterapi_io_key_here":
        print("ERROR: You need to set your API key!")
        print("1. Open the .env file")
        print("2. Replace 'your_twitterapi_io_key_here' with your real key from twitterapi.io")
        exit()

    print(f"API Key loaded: {API_KEY[:8]}...{API_KEY[-4:]}")
    print("Fetching tweets from @saylor...\n")

    tweets = get_user_tweets("saylor")

    if not tweets:
        print("No tweets returned. Check your API key and try again.")
    else:
        print(f"SUCCESS! Got {len(tweets)} tweets.\n")
        print("=" * 60)

        for i, tweet in enumerate(tweets[:5]):
            info = extract_tweet_info(tweet)
            print(f"\nTweet #{i+1}")
            print(f"  Date:    {info['created_at']}")
            print(f"  Text:    {info['text']}")
            print(f"  Likes:   {info['like_count']:,}")
            print(f"  RTs:     {info['retweet_count']:,}")
            print(f"  Views:   {info['view_count']:,}")
            print(f"  Link:    {info['url']}")
            print(f"  Reply?:  {info['is_reply']}")
            print("-" * 60)
