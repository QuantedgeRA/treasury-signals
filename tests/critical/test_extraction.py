"""
Critical-path regression tests for SEC-filing amount extraction.

These lock in the stress-test fixes: btc_amount is the TRANSACTED delta (never a
holdings total), and usd_amount scales per-match (not by a doc-wide guess). A
regression here puts a wrong number into a customer alert / the reconciler —
the single highest-trust failure mode for the product. Pure functions, no DB.
"""
import pytest

from treasury_signals.scanners import edgar_realtime as e


class TestBtcTransactionExtraction:
    @pytest.mark.parametrize("text,expected", [
        ("used these proceeds to purchase 24,869 bitcoin", 24869),       # base-form verb
        ("added more than 1,600 Bitcoin to our strategic reserve", 1600),  # "more than" filler
        ("Acquired ~803 Bitcoin through strategic purchases", 803),      # ~ prefix
        ("sold 1,200 BTC and holds 10,000 bitcoin", 1200),               # sale leg, not holdings
        ("acquired approximately 5,000 bitcoin, now holds 843,738 BTC", 5000),
    ])
    def test_transacted_amount_extracted(self, text, expected):
        assert e._extract_btc_amount(text) == expected

    @pytest.mark.parametrize("text", [
        "BTC Gain of 4,391 bitcoin, holds 843,738 bitcoin",               # a metric, not a buy
        "a starting amount of 100,000 bitcoin will result in 10,000 BTC Gain",
        "Maintained strong liquidity position with 15,679 bitcoin",       # holdings, not a txn
        "the company holds approximately 226,331 bitcoin",
    ])
    def test_non_transaction_returns_zero(self, text):
        # No acquisition/disposal verb adjacent → 0. Must NEVER fall back to the
        # holdings total (the corruption that announced fake giant purchases).
        assert e._extract_btc_amount(text) == 0

    def test_holdings_total_available_separately(self):
        # The total is still extractable for logging/ops — just not as btc_amount.
        assert e._extract_btc_holdings("the company holds approximately 226,331 bitcoin") == 226331


class TestUsdExtraction:
    def test_million_stays_million(self):
        # The original bug inflated "$871 million" to $871 billion via a doc-wide scan.
        assert e._extract_usd_amount("$871 million convertible notes") == 871_000_000

    def test_billion_word(self):
        assert e._extract_usd_amount("raised $2 billion to buy bitcoin") == 2_000_000_000

    def test_b_suffix_is_billion(self):
        # "$871b" / "$871B" is standard shorthand for billion — correct, not a bug.
        assert e._extract_usd_amount("$871b in ATM capacity") == 871_000_000_000

    def test_m_suffix_is_million(self):
        assert e._extract_usd_amount("acquired for $450 m") == 450_000_000
