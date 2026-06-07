"""
Critical-path regression tests for the purchase-dedup natural key.

The natural key (normalize_ticker, filing_date[:10], btc_amount) IS the dedup
guarantee (migration 0022). It must mirror the SQL dedup_normalize_ticker()
exactly and — importantly — must NOT strip the Japanese ".T" suffix (3350.T is
a distinct entity), while it DOES strip suffixes like ".US"/".HK"/".L". Pure
functions, no DB.
"""
from treasury_signals.pipelines import purchase_keys as k


class TestNormalizeTicker:
    def test_plain_ticker_unchanged(self):
        assert k.normalize_ticker("MSTR") == "MSTR"

    def test_lowercase_and_trim(self):
        assert k.normalize_ticker("  mstr  ") == "MSTR"

    def test_strips_known_exchange_suffix(self):
        assert k.normalize_ticker("MSTR.US") == "MSTR"
        assert k.normalize_ticker("9988.HK") == "9988"
        assert k.normalize_ticker("RIOT.L") == "RIOT"

    def test_keeps_japanese_T_suffix(self):
        # Intentionally NOT in SUFFIXES — Metaplanet 3350.T must stay distinct.
        assert k.normalize_ticker("3350.T") == "3350.T"

    def test_only_one_suffix_stripped(self):
        # Strips exactly one known suffix, not recursively.
        assert k.normalize_ticker("FOO.US") == "FOO"

    def test_empty(self):
        assert k.normalize_ticker("") == ""
        assert k.normalize_ticker(None) == ""


class TestNaturalKey:
    def test_date_truncated_to_day(self):
        # "2026-04-06" and "2026-04-06T00:00:00" must collide (same key).
        a = k.natural_key("MSTR", "2026-04-06", 4871)
        b = k.natural_key("MSTR", "2026-04-06T00:00:00+00:00", 4871.0)
        assert a == b

    def test_amount_int_float_equal(self):
        assert k.natural_key("MSTR", "2026-04-06", 4871) == k.natural_key("MSTR", "2026-04-06", 4871.0)

    def test_suffix_normalized_in_key(self):
        assert k.natural_key("MSTR.US", "2026-04-06", 100)[0] == "MSTR"

    def test_bad_amount_coerces_to_zero(self):
        assert k.natural_key("MSTR", "2026-04-06", "not-a-number")[2] == 0.0
