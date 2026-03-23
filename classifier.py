"""
classifier.py — Smart Signal Classifier v2.0
-----------------------------------------------
Multi-dimensional weighted scoring system that analyzes tweets
across 6 dimensions: language patterns, author authority, context,
timing, financial references, and behavioral signals.

Improvements over v1:
- Weighted keyword categories (not flat matching)
- Context awareness (distinguishing "we bought" from "should we buy")
- Author authority tiers with company role weighting
- Behavioral signals (tweet length, media presence)
- Negation detection ("not buying", "didn't accumulate")
- Sarcasm/question filtering ("should we buy?", "imagine if...")
- Combo multipliers (strong keyword + key author = boosted)
- Dimension breakdown for transparency

Usage:
    from classifier import classify_tweet, get_signal_label

    result = classify_tweet(
        tweet_text="Stretch the Orange Dots",
        author_username="saylor",
        created_at="2026-03-15T11:47:44Z",
    )
    # result = {"score": 85, "is_signal": True, "reasons": [...], "dimensions": {...}}
"""

import re
from datetime import datetime
from logger import get_logger

logger = get_logger(__name__)


# ============================================
# DIMENSION 1: LANGUAGE PATTERNS
# ============================================

# Saylor-specific coded language (historically precedes purchases)
SAYLOR_CODED = {
    "orange dots": 30, "orange dot": 30, "more orange": 25,
    "stretch the orange": 30, "back to orange": 25,
    "the orange century": 25, "second century": 20,
    "third century": 20, "fourth century": 20,
    "bigger bag": 20, "bigger orange bag": 25,
    "need a bigger": 15,
}

# Direct purchase language (any author)
PURCHASE_DIRECT = {
    "acquired": 25, "purchased": 25, "bought": 20,
    "added to our treasury": 30, "added to treasury": 30,
    "increased our bitcoin": 25, "increased our btc": 25,
    "treasury now holds": 20, "now hold": 15,
    "bitcoin acquisition": 25, "btc acquisition": 25,
    "capital deployment": 15, "deployed capital": 15,
}

# Accumulation intent language
ACCUMULATION_INTENT = {
    "accumulate": 12, "accumulation": 12, "accumulating": 12,
    "stack": 10, "stacking": 10, "stacked": 10,
    "buy the dip": 12, "buying the dip": 12,
    "adding more": 10, "adding bitcoin": 12,
    "dollar cost average": 8, "dca": 8,
    "deploying": 10, "raising capital": 15,
    "convertible note": 15, "at-the-market": 15, "atm offering": 15,
}

# Bitcoin conviction language (weaker signal alone, strong in combo)
CONVICTION = {
    "bitcoin yield": 8, "btc yield": 8,
    "digital gold": 5, "digital capital": 8,
    "hard money": 5, "sound money": 5,
    "reserve asset": 8, "strategic reserve": 10,
    "21 million": 5, "hard cap": 5,
    "orange pill": 5, "hyperbitcoinization": 5,
    "bitcoin standard": 5, "number go up": 3,
}

# Tracker/disclosure URLs (strong signal — usually accompanies purchase)
TRACKER_PATTERNS = {
    "strategytracker": 20, "saylortracker": 20,
    "bitcointreasuries": 15,
    "8-k": 15, "8k filing": 15,
    "form 8-k": 20, "sec.gov": 10,
}

# ============================================
# DIMENSION 2: NOISE & NEGATION
# ============================================

NOISE_PHRASES = [
    "good morning", "happy birthday", "congratulations", "happy new year",
    "podcast", "interview", "speaking at", "join me at", "join us",
    "hiring", "job opening", "apply now", "we're hiring",
    "earnings call", "conference call", "quarterly results",
    "rt if", "like if", "who agrees", "unpopular opinion",
    "giveaway", "airdrop", "free bitcoin",
    "not financial advice", "nfa", "dyor",
    "thoughts?", "what do you think",
]

NEGATION_PATTERNS = [
    r"(?:not|never|didn'?t|won'?t|haven'?t|shouldn'?t|wouldn'?t)\s+(?:buy|bought|purchase|accumulate|stack|add)",
    r"(?:stop|quit|pause|halt)\s+(?:buying|purchasing|accumulating|stacking)",
    r"should\s+(?:we|i|they)\s+(?:buy|purchase|accumulate)",
    r"(?:if|imagine|what if)\s+.*(?:buy|bought|purchase)",
]

QUESTION_INDICATORS = [
    "?", "should we", "should i", "do you think",
    "what if", "imagine if", "hypothetically",
    "would you", "considering",
]

# ============================================
# DIMENSION 3: AUTHOR AUTHORITY
# ============================================

AUTHOR_TIER1 = {
    "saylor": {"score": 30, "company": "Strategy", "role": "Executive Chairman"},
    "michael_saylor": {"score": 30, "company": "Strategy", "role": "Executive Chairman"},
}

AUTHOR_TIER2 = {
    "strategy": {"score": 15, "company": "Strategy", "role": "Corporate"},
    "phongle_": {"score": 18, "company": "Strategy", "role": "CFO"},
    "marathondh": {"score": 15, "company": "MARA", "role": "Corporate"},
    "faborode": {"score": 18, "company": "MARA", "role": "CEO"},
    "metaplanet_jp": {"score": 15, "company": "Metaplanet", "role": "Corporate"},
    "simongerovich": {"score": 18, "company": "Metaplanet", "role": "CEO"},
    "jackmallers": {"score": 18, "company": "Twenty One", "role": "CEO"},
    "brian_armstrong": {"score": 12, "company": "Coinbase", "role": "CEO"},
}

AUTHOR_TIER3 = {
    "riotplatforms": {"score": 8, "company": "Riot", "role": "Corporate"},
    "haboratory": {"score": 8, "company": "Hut 8", "role": "Corporate"},
    "cleanspark": {"score": 8, "company": "CleanSpark", "role": "Corporate"},
    "bitfarms_io": {"score": 8, "company": "Bitfarms", "role": "Corporate"},
    "kulrtech": {"score": 8, "company": "KULR", "role": "Corporate"},
    "semlerscientific": {"score": 8, "company": "Semler", "role": "Corporate"},
    "elonmusk": {"score": 10, "company": "Tesla", "role": "CEO"},
    "blocks": {"score": 8, "company": "Block", "role": "Corporate"},
    "jack": {"score": 10, "company": "Block", "role": "Founder"},
}

ALL_AUTHORS = {}
ALL_AUTHORS.update(AUTHOR_TIER1)
ALL_AUTHORS.update(AUTHOR_TIER2)
ALL_AUTHORS.update(AUTHOR_TIER3)

# ============================================
# DIMENSION 4: FINANCIAL REFERENCES
# ============================================

FINANCIAL_TICKERS = {
    "$STRC": 12, "$STRF": 12, "$STRK": 12,
    "$MSTR": 8, "$BTC": 5,
    "$MARA": 6, "$RIOT": 6, "$CLSK": 6,
    "$HUT": 6, "$GME": 6, "$COIN": 5,
}


# ============================================
# MAIN CLASSIFIER
# ============================================

def classify_tweet(tweet_text, author_username, created_at, is_reply=False):
    """
    Multi-dimensional tweet analysis returning a signal score (0-100).

    Returns:
        dict with 'score', 'is_signal', 'reasons', 'dimensions'
    """
    score = 0
    reasons = []
    dimensions = {
        "language": 0, "author": 0, "noise": 0,
        "financial": 0, "timing": 0, "structure": 0,
        "learned": 0,
    }

    text_lower = tweet_text.lower().strip()
    author_lower = author_username.lower().strip()
    word_count = len(tweet_text.split())

    # Early exit
    if is_reply:
        return {"score": 0, "is_signal": False, "reasons": ["Skipped: reply"], "dimensions": dimensions}
    if text_lower.startswith("rt @"):
        return {"score": 0, "is_signal": False, "reasons": ["Skipped: retweet"], "dimensions": dimensions}

    # --- DIMENSION 1: LANGUAGE ---
    lang_score = 0
    for category, keywords in [
        ("Coded language", SAYLOR_CODED),
        ("Purchase language", PURCHASE_DIRECT),
        ("Accumulation intent", ACCUMULATION_INTENT),
        ("Conviction", CONVICTION),
        ("Tracker/filing", TRACKER_PATTERNS),
    ]:
        for keyword, points in keywords.items():
            if keyword in text_lower:
                lang_score += points
                reasons.append(f"{category}: '{keyword}' (+{points})")

    lang_score = min(lang_score, 55)
    dimensions["language"] = lang_score
    score += lang_score

    # --- DIMENSION 2: NOISE & NEGATION ---
    noise_penalty = 0

    for noise in NOISE_PHRASES:
        if noise in text_lower:
            noise_penalty += 15
            reasons.append(f"Noise: '{noise}' (-15)")
            break

    for pattern in NEGATION_PATTERNS:
        if re.search(pattern, text_lower):
            noise_penalty += 25
            reasons.append("Negation detected (-25)")
            break

    question_hits = sum(1 for q in QUESTION_INDICATORS if q in text_lower)
    if question_hits >= 1:
        q_penalty = min(question_hits * 8, 20)
        noise_penalty += q_penalty
        reasons.append(f"Question/hypothetical ({question_hits} indicators, -{q_penalty})")

    noise_penalty = min(noise_penalty, 40)
    dimensions["noise"] = -noise_penalty
    score -= noise_penalty

    # --- DIMENSION 3: AUTHOR AUTHORITY ---
    author_score = 0
    author_info = ALL_AUTHORS.get(author_lower)

    if author_info:
        author_score = author_info["score"]
        reasons.append(f"Author: @{author_username} ({author_info['role']}, {author_info['company']}) (+{author_score})")

        # Combo: key author + strong language
        if author_score >= 25 and lang_score >= 20:
            author_score += 10
            reasons.append("Combo: key author + strong signal (+10)")

    dimensions["author"] = author_score
    score += author_score

    # --- DIMENSION 4: FINANCIAL REFERENCES ---
    fin_score = 0

    ticker_matches = re.findall(r'\$[A-Z]{2,5}', tweet_text)
    for ticker in ticker_matches:
        if ticker in FINANCIAL_TICKERS:
            points = FINANCIAL_TICKERS[ticker]
            fin_score += points
            reasons.append(f"Ticker: {ticker} (+{points})")

    if re.search(r'\b[\d,]+\.?\d*\s*(?:btc|bitcoin|sats|satoshis)\b', text_lower):
        fin_score += 10
        reasons.append("BTC amount reference (+10)")

    if re.search(r'\$[\d,]+\.?\d*\s*[bmk](?:illion)?', text_lower):
        fin_score += 8
        reasons.append("Dollar amount reference (+8)")

    fin_score = min(fin_score, 25)
    dimensions["financial"] = fin_score
    score += fin_score

    # --- DIMENSION 5: TIMING ---
    timing_score = 0
    try:
        dt = None
        for fmt in ["%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
            try:
                dt = datetime.strptime(created_at, fmt)
                break
            except ValueError:
                continue

        if dt:
            if dt.weekday() >= 5:
                timing_score += 8
                reasons.append(f"Weekend post ({dt.strftime('%A')}) (+8)")
            if dt.hour >= 22 or dt.hour <= 5:
                timing_score += 5
                reasons.append(f"Unusual hour ({dt.hour}:00) (+5)")
    except Exception as e:
        logger.debug(f"Timing parse failed: {e}")

    timing_score = min(timing_score, 12)
    dimensions["timing"] = timing_score
    score += timing_score

    # --- DIMENSION 6: STRUCTURAL SIGNALS ---
    struct_score = 0

    if author_info and author_info["score"] >= 25:
        if word_count <= 5:
            struct_score += 12
            reasons.append(f"Short/cryptic ({word_count} words) from key author (+12)")
        elif word_count <= 10:
            struct_score += 5
            reasons.append(f"Brief post ({word_count} words) from key author (+5)")
    elif word_count <= 5:
        struct_score += 3
        reasons.append(f"Short post ({word_count} words) (+3)")

    if ("t.co/" in text_lower or "pic.twitter" in text_lower) and author_info and author_info["score"] >= 15:
        struct_score += 5
        reasons.append("Contains media from tracked author (+5)")

    caps_words = [w for w in tweet_text.split() if w.isupper() and len(w) > 2 and w not in ["BTC", "USD", "ETF", "SEC", "CEO", "CFO"]]
    if len(caps_words) >= 2:
        struct_score += 3
        reasons.append(f"Emphasis: {len(caps_words)} capitalized words (+3)")

    struct_score = min(struct_score, 15)
    dimensions["structure"] = struct_score
    score += struct_score

    # --- DIMENSION 7: LEARNED ADJUSTMENTS (Phase 15) ---
    learned_score = 0
    try:
        from feedback_loop import feedback_engine
        # Apply keyword adjustments
        for category_keywords in [SAYLOR_CODED, PURCHASE_DIRECT, ACCUMULATION_INTENT, CONVICTION, TRACKER_PATTERNS]:
            for keyword in category_keywords:
                if keyword in text_lower:
                    adj = feedback_engine.get_keyword_adjustment(keyword)
                    if adj != 0:
                        learned_score += adj

        # Apply author adjustment
        author_adj = feedback_engine.get_author_adjustment(author_lower)
        if author_adj != 0:
            learned_score += author_adj

        if learned_score != 0:
            learned_score = max(-15, min(learned_score, 15))  # Cap adjustment range
            reasons.append(f"Learned adjustment: {learned_score:+.1f} (from accuracy feedback)")
    except ImportError:
        pass
    except Exception:
        pass

    dimensions["learned"] = round(learned_score)
    score += round(learned_score)

    # --- FINAL ---
    score = max(0, min(score, 100))
    is_signal = score >= 40

    if not reasons:
        reasons.append("No signal patterns detected")

    if is_signal:
        logger.debug(f"Signal: @{author_username} scored {score}/100 — dims: {dimensions}")

    return {
        "score": score,
        "is_signal": is_signal,
        "reasons": reasons,
        "dimensions": dimensions,
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


def get_dimension_breakdown(dimensions):
    """Format dimension scores as a readable string."""
    labels = {
        "language": "📝 Lang", "author": "👤 Author", "noise": "🔇 Noise",
        "financial": "💰 Fin", "timing": "⏰ Time", "structure": "📐 Struct",
        "learned": "🧠 Learn",
    }
    parts = [f"{labels[k]}: {v:+d}" for k, v in dimensions.items() if v != 0]
    return " | ".join(parts) if parts else "No dimensions scored"


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    logger.info("Testing Smart Classifier v2.0")
    print(f"\n{'='*70}")
    print("  SMART SIGNAL CLASSIFIER v2.0 — TEST SUITE")
    print(f"{'='*70}\n")

    test_tweets = [
        {"text": "Stretch the Orange Dots. https://t.co/WMVPUxlIcx", "author": "saylor", "date": "Sun Mar 15 11:47:44 +0000 2026"},
        {"text": "More Orange", "author": "saylor", "date": "Sat Feb 01 10:00:00 +0000 2026"},
        {"text": "Strategy has acquired 22,048 BTC for ~$1.92B. $MSTR", "author": "saylor", "date": "Mon Mar 10 08:00:00 +0000 2026"},
        {"text": "Stacking sats. Bitcoin yield strategy is working. $MSTR", "author": "phongle_", "date": "Tue Mar 11 14:00:00 +0000 2026"},
        {"text": "We continue to accumulate Bitcoin as a strategic reserve asset.", "author": "metaplanet_jp", "date": "Wed Mar 12 09:00:00 +0000 2026"},
        {"text": "Good morning everyone! Beautiful day in Miami.", "author": "saylor", "date": "Mon Mar 10 08:00:00 +0000 2026"},
        {"text": "Join me at Bitcoin 2026 conference this weekend!", "author": "saylor", "date": "Thu Mar 13 10:00:00 +0000 2026"},
        {"text": "Riot Platforms Reports Full Year 2025 Results", "author": "RiotPlatforms", "date": "Tue Mar 03 15:01:29 +0000 2026"},
        {"text": "Should we buy more Bitcoin? What do you think?", "author": "strategy", "date": "Mon Mar 10 12:00:00 +0000 2026"},
        {"text": "We have not bought any Bitcoin this quarter.", "author": "strategy", "date": "Mon Mar 10 12:00:00 +0000 2026"},
        {"text": "MARA acquired 1,000 BTC at $72,000. Treasury now holds 46,374 BTC.", "author": "marathondh", "date": "Fri Mar 14 16:00:00 +0000 2026"},
    ]

    for i, t in enumerate(test_tweets):
        result = classify_tweet(t["text"], t["author"], t["date"])
        label = get_signal_label(result["score"])
        dims = get_dimension_breakdown(result["dimensions"])

        print(f"  #{i+1}  @{t['author']}: \"{t['text'][:55]}{'...' if len(t['text']) > 55 else ''}\"")
        print(f"       Score: {result['score']}/100 {label}")
        print(f"       Dims:  {dims}")
        print(f"       Signal: {'YES' if result['is_signal'] else 'no'}")
        print()

    logger.info("Classifier v2.0 test complete")
