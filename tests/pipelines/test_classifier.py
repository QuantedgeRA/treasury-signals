"""
Tests for treasury_signals.pipelines.classifier.

The classifier turns raw tweets into 0-100 signal scores. Bugs here = wrong
alerts to paying customers (false positives wake people up at 3am, false
negatives miss real treasury moves). Tests focus on behaviors that
reflect real production scenarios — known signals from real tweets,
known noise from podcast/birthday/conference posts, and the bounds
contract (0-100, threshold at 40).
"""

import pytest
from treasury_signals.pipelines.classifier import (
    classify_tweet,
    get_signal_label,
    get_dimension_breakdown,
    ALL_AUTHORS,
)


# ─── Early-exit cases ───────────────────────────────────────────────────────

class TestEarlyExits:
    def test_reply_returns_zero(self):
        result = classify_tweet("acquired 1000 BTC", "saylor", "2026-05-08", is_reply=True)
        assert result["score"] == 0
        assert result["is_signal"] is False
        assert "reply" in result["reasons"][0].lower()

    def test_retweet_returns_zero(self):
        result = classify_tweet("RT @other we bought bitcoin", "saylor", "2026-05-08")
        assert result["score"] == 0
        assert result["is_signal"] is False
        assert "retweet" in result["reasons"][0].lower()


# ─── Strong signals (true positives) ────────────────────────────────────────

class TestStrongSignals:
    def test_saylor_orange_dots_is_signal(self):
        # "Orange Dots" is Saylor's known coded-purchase signal
        result = classify_tweet(
            "Stretch the Orange Dots. https://t.co/abc",
            "saylor",
            "Sun Mar 15 11:47:44 +0000 2026",
        )
        assert result["score"] >= 40, f"expected signal, got {result['score']}"
        assert result["is_signal"] is True

    def test_direct_purchase_announcement_is_signal(self):
        result = classify_tweet(
            "Strategy has acquired 22,048 BTC for ~$1.92B. $MSTR",
            "saylor",
            "Mon Mar 10 08:00:00 +0000 2026",
        )
        assert result["score"] >= 40
        assert result["is_signal"] is True

    def test_corporate_account_purchase_is_signal(self):
        result = classify_tweet(
            "MARA acquired 1,000 BTC at $72,000. Treasury now holds 46,374 BTC.",
            "marathondh",
            "Fri Mar 14 16:00:00 +0000 2026",
        )
        assert result["score"] >= 40
        assert result["is_signal"] is True

    def test_metaplanet_accumulation_intent_is_signal(self):
        result = classify_tweet(
            "We continue to accumulate Bitcoin as a strategic reserve asset.",
            "metaplanet_jp",
            "Wed Mar 12 09:00:00 +0000 2026",
        )
        assert result["score"] >= 40


# ─── Noise / false-positive defenses ────────────────────────────────────────

class TestNoiseRejection:
    def test_good_morning_post_not_signal(self):
        result = classify_tweet(
            "Good morning everyone! Beautiful day in Miami.",
            "saylor",
            "Mon Mar 10 08:00:00 +0000 2026",
        )
        assert result["is_signal"] is False, f"good-morning shouldn't signal, got {result['score']}"

    def test_conference_invite_not_signal(self):
        result = classify_tweet(
            "Join me at Bitcoin 2026 conference this weekend!",
            "saylor",
            "Thu Mar 13 10:00:00 +0000 2026",
        )
        assert result["is_signal"] is False

    def test_earnings_announcement_not_signal(self):
        # Quarterly earnings posts use bullish language but aren't purchase signals
        result = classify_tweet(
            "Riot Platforms Reports Full Year 2025 Results",
            "riotplatforms",
            "Tue Mar 03 15:01:29 +0000 2026",
        )
        assert result["is_signal"] is False

    def test_question_about_buying_not_signal(self):
        # "Should we buy?" is a question, not a purchase
        result = classify_tweet(
            "Should we buy more Bitcoin? What do you think?",
            "strategy",
            "Mon Mar 10 12:00:00 +0000 2026",
        )
        assert result["is_signal"] is False

    def test_negation_not_signal(self):
        # "We have NOT bought" should score low despite "bought" keyword
        result = classify_tweet(
            "We have not bought any Bitcoin this quarter.",
            "strategy",
            "Mon Mar 10 12:00:00 +0000 2026",
        )
        assert result["is_signal"] is False


# ─── Author authority impact ────────────────────────────────────────────────

class TestAuthorAuthority:
    def test_unknown_author_scores_lower(self):
        # Same content from unknown vs known author — known should score higher
        text = "We continue to accumulate Bitcoin"
        date = "Mon Mar 10 08:00:00 +0000 2026"
        unknown = classify_tweet(text, "random_user_no_one_knows", date)
        known = classify_tweet(text, "saylor", date)
        assert known["score"] > unknown["score"]

    def test_combo_bonus_for_key_author_plus_signal(self):
        # Saylor (rank 30) + strong language (>=20) gets +10 combo bonus
        result = classify_tweet(
            "We have acquired bitcoin",
            "saylor",
            "Mon Mar 10 08:00:00 +0000 2026",
        )
        # Look for the combo bonus reason
        assert any("combo" in r.lower() for r in result["reasons"]), \
            f"expected combo bonus, reasons: {result['reasons']}"

    def test_all_known_authors_have_required_fields(self):
        # Catches accidental schema breakage in the AUTHOR_TIER dicts
        for author, info in ALL_AUTHORS.items():
            assert "score" in info, f"author {author} missing 'score'"
            assert "company" in info, f"author {author} missing 'company'"
            assert "role" in info, f"author {author} missing 'role'"
            assert isinstance(info["score"], int), f"author {author} score not int"
            assert info["score"] > 0, f"author {author} score must be positive"


# ─── Score bounds contract ──────────────────────────────────────────────────

class TestScoreBounds:
    def test_score_never_exceeds_100(self):
        # Stack every signal possible — score must still cap at 100
        result = classify_tweet(
            "Strategy has acquired 22048 BTC. Stretch the Orange Dots. "
            "Bitcoin acquisition. $STRC $MSTR. Form 8-K. saylortracker. "
            "Adding more bitcoin to our treasury. capital deployment.",
            "saylor",
            "Sun Mar 15 23:00:00 +0000 2026",  # weekend + late night
        )
        assert 0 <= result["score"] <= 100

    def test_score_never_below_zero(self):
        # Stack noise + negation — score floors at 0, doesn't go negative
        result = classify_tweet(
            "Good morning! Happy birthday. Not buying. Should we accumulate? "
            "Podcast tomorrow. Hiring. Giveaway.",
            "saylor",
            "2026-05-08",
        )
        assert result["score"] >= 0

    def test_signal_threshold_is_40(self):
        # The is_signal=True boundary is score >= 40
        # Empirically constructed: a tweet that should land just over the threshold
        result = classify_tweet(
            "We acquired bitcoin yesterday",
            "saylor",
            "2026-05-08",
        )
        if result["score"] >= 40:
            assert result["is_signal"] is True
        else:
            assert result["is_signal"] is False


# ─── Label mapping ──────────────────────────────────────────────────────────

class TestSignalLabel:
    def test_very_high(self):
        assert "VERY HIGH" in get_signal_label(80)
        assert "VERY HIGH" in get_signal_label(100)

    def test_high(self):
        assert "HIGH" in get_signal_label(60)
        assert "HIGH" in get_signal_label(79)
        assert "VERY HIGH" not in get_signal_label(60)

    def test_medium(self):
        assert "MEDIUM" in get_signal_label(40)
        assert "MEDIUM" in get_signal_label(59)

    def test_low(self):
        assert "LOW" in get_signal_label(20)
        assert "LOW" in get_signal_label(39)

    def test_none(self):
        assert "NONE" in get_signal_label(0)
        assert "NONE" in get_signal_label(19)


# ─── Dimension breakdown formatter ──────────────────────────────────────────

class TestDimensionBreakdown:
    def test_formats_nonzero_dimensions(self):
        out = get_dimension_breakdown({"language": 30, "author": 15, "noise": 0})
        assert "Lang" in out
        assert "Author" in out
        # Zero dimensions should be omitted
        assert "Noise" not in out

    def test_handles_all_zero(self):
        out = get_dimension_breakdown({"language": 0, "author": 0, "noise": 0})
        assert "No dimensions" in out

    def test_includes_signs(self):
        out = get_dimension_breakdown({"language": 30, "noise": -10})
        assert "+30" in out
        assert "-10" in out


# ─── Result shape contract ──────────────────────────────────────────────────

class TestResultShape:
    def test_result_has_required_keys(self):
        result = classify_tweet("hello", "saylor", "2026-05-08")
        assert "score" in result
        assert "is_signal" in result
        assert "reasons" in result
        assert "dimensions" in result
        assert isinstance(result["score"], int)
        assert isinstance(result["is_signal"], bool)
        assert isinstance(result["reasons"], list)
        assert isinstance(result["dimensions"], dict)

    def test_dimensions_has_all_seven(self):
        result = classify_tweet("hello", "saylor", "2026-05-08")
        for dim in ["language", "author", "noise", "financial", "timing", "structure", "learned"]:
            assert dim in result["dimensions"], f"missing dimension: {dim}"
