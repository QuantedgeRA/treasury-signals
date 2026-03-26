"""
monitored_accounts.py — Multi-Company Executive Monitoring Config
------------------------------------------------------------------
Add accounts here to expand signal monitoring beyond Saylor.
The classifier will analyze tweets from ALL accounts listed.

Usage:
    from monitored_accounts import MONITORED_ACCOUNTS
    
    # In your Twitter scanner:
    for account in MONITORED_ACCOUNTS:
        tweets = fetch_tweets(account['username'])
        for tweet in tweets:
            score = classify(tweet, account['company'], account['weight'])
"""

MONITORED_ACCOUNTS = [
    # ━━━ Strategy (MicroStrategy) ━━━
    {"username": "saylor", "company": "Strategy", "ticker": "MSTR", "role": "Executive Chairman", "weight": 1.0},
    {"username": "phaboroshi", "company": "Strategy", "ticker": "MSTR", "role": "CEO & President", "weight": 0.9},

    # ━━━ MARA Holdings (Marathon Digital) ━━━
    {"username": "FredThiel", "company": "MARA Holdings", "ticker": "MARA", "role": "Chairman & CEO", "weight": 0.9},
    {"username": "MarathonDH", "company": "MARA Holdings", "ticker": "MARA", "role": "Corporate", "weight": 0.7},

    # ━━━ Riot Platforms ━━━
    {"username": "JasonLes_", "company": "Riot Platforms", "ticker": "RIOT", "role": "CEO", "weight": 0.85},
    {"username": "RiotPlatforms", "company": "Riot Platforms", "ticker": "RIOT", "role": "Corporate", "weight": 0.7},

    # ━━━ CleanSpark ━━━
    {"username": "ZachBradford", "company": "CleanSpark", "ticker": "CLSK", "role": "CEO", "weight": 0.85},
    {"username": "CleanSpark_Inc", "company": "CleanSpark", "ticker": "CLSK", "role": "Corporate", "weight": 0.7},

    # ━━━ Hut 8 Mining ━━━
    {"username": "AsherGenoot", "company": "Hut 8", "ticker": "HUT", "role": "CEO", "weight": 0.85},
    {"username": "Hut8Corp", "company": "Hut 8", "ticker": "HUT", "role": "Corporate", "weight": 0.7},

    # ━━━ Twenty One Capital ━━━
    {"username": "JackMallers", "company": "Twenty One Capital", "ticker": "XXI", "role": "CEO", "weight": 0.9},
    {"username": "TwentyOneCap", "company": "Twenty One Capital", "ticker": "XXI", "role": "Corporate", "weight": 0.7},

    # ━━━ Bitfarms ━━━
    {"username": "Bitfarms_io", "company": "Bitfarms", "ticker": "BITF", "role": "Corporate", "weight": 0.7},

    # ━━━ Core Scientific ━━━
    {"username": "CoreScientific", "company": "Core Scientific", "ticker": "CORZ", "role": "Corporate", "weight": 0.7},

    # ━━━ Metaplanet ━━━
    {"username": "siaboroshi", "company": "Metaplanet", "ticker": "3350", "role": "CEO", "weight": 0.9},
    {"username": "Metaplanet_JP", "company": "Metaplanet", "ticker": "3350", "role": "Corporate", "weight": 0.7},

    # ━━━ Tesla ━━━
    {"username": "elonmusk", "company": "Tesla", "ticker": "TSLA", "role": "CEO", "weight": 0.5},  # Lower weight — BTC tweets are rare

    # ━━━ Block (Square) ━━━
    {"username": "jack", "company": "Block", "ticker": "SQ", "role": "CEO", "weight": 0.6},
    {"username": "blocks", "company": "Block", "ticker": "SQ", "role": "Corporate", "weight": 0.5},

    # ━━━ Coinbase ━━━
    {"username": "brian_armstrong", "company": "Coinbase", "ticker": "COIN", "role": "CEO", "weight": 0.5},

    # ━━━ Semler Scientific ━━━
    {"username": "SemlerSci", "company": "Semler Scientific", "ticker": "SMLR", "role": "Corporate", "weight": 0.8},
]

# Convenience: get all usernames as a flat list
ALL_USERNAMES = [a["username"] for a in MONITORED_ACCOUNTS]

# Convenience: lookup company info by username
USERNAME_MAP = {a["username"].lower(): a for a in MONITORED_ACCOUNTS}

def get_account_info(username):
    """Get company/ticker/role for a monitored username."""
    return USERNAME_MAP.get(username.lower().lstrip('@'))

def get_accounts_for_company(ticker):
    """Get all monitored accounts for a specific company ticker."""
    return [a for a in MONITORED_ACCOUNTS if a["ticker"] == ticker]
