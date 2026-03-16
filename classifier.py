"""
classifier.py
-------------
The signal detection brain.
Analyzes tweets and scores them as potential purchase hints.

This starts as simple keyword/pattern matching (V1).
You'll improve it over time as you learn more patterns.
"""

import re
from datetime import datetime


# ============================================
# SIGNAL KEYWORDS AND PATTERNS
# ============================================

# Words/phrases that appear in known purchase hints
STRONG_KEYWORDS = [
    "orange dots", "orange dot", "more orange", "stretch the orange",
    "back to orange", "the orange century",
    "second century", "third century",
    "bigger bag", "bigger orange bag",
    "need a bigger",
    "saylor tracker", "strategytracker",
]

MEDIUM_KEYWORDS = [
    "accumulate", "accumulation", "stack", "stacking",
    "buy the dip", "adding more",
    "bitcoin yield", "btc yield",
    "digital credit", "digital gold",
    "orange pill",
    "21 million", "hard cap",
    "treasury", "reserve asset",
]

# Words that suggest it's NOT a purchase signal
NOISE_KEYWORDS = [
    "good morning", "happy birthday", "congratulations",
    "podcast", "interview", "speaking at", "join me",
    "hiring", "job opening", "apply",
    "earnings call", "conference call",
    "rt if", "like if", "who agrees",
]

# Known high-priority signal accounts
HIGH_SIGNAL_AUTHORS = [
    "saylor", "michael_saylor",
]

MEDIUM_SIGNAL_AUTHORS = [
    "strategy", "phongle_",
    "marathondh", "faborode",
    "metaplanet_jp", "simongerovich",
]

# URLs that often appear in purchase hint posts
TRACKER_URLS = [
    "strategytracker", "saylortracker",
    "bitcointreasuries",
]


def classify_tweet(tweet_text, author_username, created_at, is_reply=False):
    """
    Analyze a tweet and return a signal score (0-100) with reasons.
    
    Args:
        tweet_text: The tweet content
        author_username: The X handle (without @)
        created_at: When the tweet was posted
        is_reply: Whether this is a reply to someone
    
    Returns:
        dict with 'score', 'is_signal', and 'reasons'
    """
    
    score = 0
    reasons = []
    text_lower = tweet_text.lower()
    author_lower = author_username.lower()
    
    # ---- RULE 1: Skip replies (signals are almost always original posts) ----
    if is_reply:
        return {"score": 0, "is_signal": False, "reasons": ["Skipped: reply tweet"]}
    
    # ---- RULE 2: Skip retweets (we want original posts) ----
    if text_lower.startswith("rt @"):
        return {"score": 0, "is_signal": False, "reasons": ["Skipped: retweet"]}
    
    # ---- RULE 3: Check for noise keywords (likely not a signal) ----
    for noise in NOISE_KEYWORDS:
        if noise in text_lower:
            score -= 15
            reasons.append(f"Noise keyword: '{noise}' (-15)")
            break  # Only penalize once
    
    # ---- RULE 4: Author weight ----
    if author_lower in HIGH_SIGNAL_AUTHORS:
        score += 25
        reasons.append(f"High-priority author: @{author_username} (+25)")
    elif author_lower in MEDIUM_SIGNAL_AUTHORS:
        score += 10
        reasons.append(f"Medium-priority author: @{author_username} (+10)")
    
    # ---- RULE 5: Strong keywords (known purchase hint phrases) ----
    strong_matches = []
    for keyword in STRONG_KEYWORDS:
        if keyword in text_lower:
            strong_matches.append(keyword)
    
    if strong_matches:
        keyword_score = min(len(strong_matches) * 20, 40)  # Cap at 40
        score += keyword_score
        reasons.append(f"Strong keywords: {strong_matches} (+{keyword_score})")
    
    # ---- RULE 6: Medium keywords ----
    medium_matches = []
    for keyword in MEDIUM_KEYWORDS:
        if keyword in text_lower:
            medium_matches.append(keyword)
    
    if medium_matches:
        keyword_score = min(len(medium_matches) * 10, 20)  # Cap at 20
        score += keyword_score
        reasons.append(f"Medium keywords: {medium_matches} (+{keyword_score})")
    
    # ---- RULE 7: Short and cryptic (purchase hints are often very short) ----
    word_count = len(tweet_text.split())
    if word_count <= 5 and author_lower in HIGH_SIGNAL_AUTHORS:
        score += 15
        reasons.append(f"Short/cryptic post ({word_count} words) from key author (+15)")
    elif word_count <= 8:
        score += 5
        reasons.append(f"Short post ({word_count} words) (+5)")
    
    # ---- RULE 8: Weekend timing (hints often come on weekends) ----
    try:
        # Parse the date - handle multiple formats
        for fmt in [
            "%a %b %d %H:%M:%S %z %Y",  # "Sun Mar 15 11:47:44 +0000 2026"
            "%Y-%m-%dT%H:%M:%S.%fZ",     # ISO format
            "%Y-%m-%d",                    # Simple date
        ]:
            try:
                dt = datetime.strptime(created_at, fmt)
                if dt.weekday() >= 5:  # Saturday=5, Sunday=6
                    score += 10
                    reasons.append(f"Posted on weekend ({dt.strftime('%A')}) (+10)")
                break
            except ValueError:
                continue
    except:
        pass  # Can't parse date, skip this rule
    
    # ---- RULE 9: Contains tracker URL ----
    for tracker in TRACKER_URLS:
        if tracker in text_lower:
            score += 20
            reasons.append(f"Contains tracker URL: '{tracker}' (+20)")
            break
    
    # ---- RULE 10: Contains BTC/Bitcoin price or number patterns ----
    if re.search(r'\b\d+[,.]?\d*\s*(btc|bitcoin|sats)\b', text_lower):
        score += 10
        reasons.append("Contains BTC amount reference (+10)")
    
    # ---- RULE 11: Mentions $STRC, $MSTR, or financial instruments ----
    ticker_matches = re.findall(r'\$[A-Z]{3,5}', tweet_text)
    btc_tickers = [t for t in ticker_matches if t in ['$STRC', '$STRF', '$STRK', '$MSTR', '$BTC']]
    if btc_tickers:
        score += 10
        reasons.append(f"Mentions tickers: {btc_tickers} (+10)")
    
    # ---- Calculate final score ----
    score = max(0, min(score, 100))  # Clamp between 0-100
    is_signal = score >= 40  # Threshold for flagging as signal
    
    if not reasons:
        reasons.append("No signal patterns detected")
    
    return {
        "score": score,
        "is_signal": is_signal,
        "reasons": reasons
    }


def get_signal_label(score):
    """Return a human-readable label for the score."""
    if score >= 80:
        return "🔴 VERY HIGH"
    elif score >= 60:
        return "🟠 HIGH"
    elif score >= 40:
        return "🟡 MEDIUM"
    elif score >= 20:
        return "🔵 LOW"
    else:
        return "⚪ NONE"


# ============================================
# QUICK TEST - Run against real Saylor tweets
# ============================================
if __name__ == "__main__":
    print("Testing Signal Classifier\n")
    print("=" * 60)
    
    # Test tweets - mix of real signals and noise
    test_tweets = [
        {
            "text": "Stretch the Orange Dots. https://t.co/WMVPUxlIcx",
            "author": "saylor",
            "created_at": "Sun Mar 15 11:47:44 +0000 2026",
            "is_reply": False,
        },
        {
            "text": "More Orange",
            "author": "saylor",
            "created_at": "Sat Feb 01 10:00:00 +0000 2026",
            "is_reply": False,
        },
        {
            "text": "The Second Century Begins",
            "author": "saylor",
            "created_at": "Sun Mar 09 18:00:00 +0000 2026",
            "is_reply": False,
        },
        {
            "text": "A Simple Theory of Digital Credit:\n\n1. Acquire a large pool of appreciating capital ($BTC).\n2. Issue credit ($STRC)",
            "author": "saylor",
            "created_at": "Sat Mar 14 14:27:44 +0000 2026",
            "is_reply": False,
        },
        {
            "text": "$STRC is now the most liquid preferred stock in the market.",
            "author": "saylor",
            "created_at": "Sat Mar 14 18:30:55 +0000 2026",
            "is_reply": False,
        },
        {
            "text": "RT @borjamartels: This was the demand for $STRC on @roxom this week.",
            "author": "saylor",
            "created_at": "Sat Mar 14 20:29:13 +0000 2026",
            "is_reply": False,
        },
        {
            "text": "Good morning everyone! Beautiful day in Miami.",
            "author": "saylor",
            "created_at": "Mon Mar 10 08:00:00 +0000 2026",
            "is_reply": False,
        },
        {
            "text": "Riot Platforms Reports Full Year 2025 Financial Results",
            "author": "RiotPlatforms",
            "created_at": "Tue Mar 03 15:01:29 +0000 2026",
            "is_reply": False,
        },
        {
            "text": "Today, @Strive announced that it has added $50 million of $STRC to its corporate treasury.",
            "author": "Strategy",
            "created_at": "Wed Mar 11 13:03:31 +0000 2026",
            "is_reply": False,
        },
        {
            "text": "99 > 98",
            "author": "saylor",
            "created_at": "Sun Feb 16 09:00:00 +0000 2026",
            "is_reply": False,
        },
    ]
    
    for i, tweet in enumerate(test_tweets):
        result = classify_tweet(
            tweet["text"],
            tweet["author"],
            tweet["created_at"],
            tweet["is_reply"]
        )
        
        label = get_signal_label(result["score"])
        
        print(f"\nTweet #{i+1}: \"{tweet['text'][:80]}...\"")
        print(f"  Author: @{tweet['author']}")
        print(f"  Score:  {result['score']}/100 {label}")
        print(f"  Signal: {result['is_signal']}")
        print(f"  Reasons:")
        for reason in result["reasons"]:
            print(f"    - {reason}")
        print("-" * 60)
    
    # Summary
    signals = [t for i, t in enumerate(test_tweets) if classify_tweet(t["text"], t["author"], t["created_at"], t["is_reply"])["is_signal"]]
    print(f"\n{len(signals)} out of {len(test_tweets)} tweets flagged as signals.")
    print("\nClassifier is working!")
