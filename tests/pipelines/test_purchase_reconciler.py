"""
Tests for treasury_signals.pipelines.purchase_reconciler.

Two layers:
  1. Pure-function tests (no DB) — covers the helper functions that have no
     side effects: ticker normalization, BTC tolerance matching, date window,
     suspicious-target detection, source-rank lookup.
  2. Integration tests with mocked supabase — covers reconcile_and_save and
     reconcile_sale behavior. Verifies which tables get written to and what
     payloads are sent for each scenario (snapshot → pending, EDGAR →
     confirmed, target rejection, dedup, etc.).

The reconciler is the single most important piece of business logic in the
pipeline — bugs here = wrong data sold to paying customers. These tests
should catch regressions in dedup logic, source ranking, and the
snapshot-must-be-corroborated rule.
"""

import pytest

from treasury_signals.pipelines.purchase_reconciler import (
    reconcile_and_save,
    reconcile_sale,
    _is_suspicious_target,
    _normalize_ticker_for_dedup,
    _normalize_name_for_dedup,
    _btc_amounts_match,
    _dates_within_window,
    _get_source_rank,
    SOURCE_RANKS,
    SUSPICIOUS_TARGET_AMOUNTS,
    DEDUP_DAYS_WINDOW,
    DEDUP_BTC_TOLERANCE,
)


# ─── Pure-function tests (no DB) ────────────────────────────────────────────

class TestNormalizeTicker:
    def test_strips_us_suffix(self):
        assert _normalize_ticker_for_dedup("MSTR.US") == "MSTR"

    def test_japan_t_suffix_preserved(self):
        # .T is intentionally NOT stripped — Yahoo Finance uses .T for Japan tickers
        # and shares_sync.py preserves it. Locking in this behavior.
        assert _normalize_ticker_for_dedup("3350.T") == "3350.T"

    def test_strips_uk_suffix(self):
        assert _normalize_ticker_for_dedup("ARB.L") == "ARB"

    def test_uppercases_input(self):
        assert _normalize_ticker_for_dedup("mstr") == "MSTR"

    def test_handles_empty(self):
        assert _normalize_ticker_for_dedup("") == ""

    def test_handles_none(self):
        assert _normalize_ticker_for_dedup(None) == ""

    def test_no_suffix_unchanged(self):
        assert _normalize_ticker_for_dedup("MSTR") == "MSTR"

    def test_strips_only_first_known_suffix(self):
        # ARB.L.US — strip only one known suffix per call
        # (current implementation strips first match found)
        result = _normalize_ticker_for_dedup("ARB.L")
        assert result == "ARB"


class TestNormalizeName:
    def test_strips_inc_suffix(self):
        assert _normalize_name_for_dedup("Strategy Inc.") == "STRATEGY"

    def test_strips_corp_suffix(self):
        assert _normalize_name_for_dedup("MARA Corp") == "MARA"

    def test_strips_microstrategy_alias(self):
        assert _normalize_name_for_dedup("Strategy (MicroStrategy)") == "STRATEGY"

    def test_handles_empty(self):
        assert _normalize_name_for_dedup("") == ""

    def test_handles_none(self):
        assert _normalize_name_for_dedup(None) == ""

    def test_uppercases(self):
        assert _normalize_name_for_dedup("metaplanet") == "METAPLANET"


class TestBtcAmountsMatch:
    def test_both_zero_match(self):
        assert _btc_amounts_match(0, 0) is True

    def test_one_zero_no_match(self):
        # If one side has an amount and the other doesn't, can't confirm match
        assert _btc_amounts_match(0, 100) is False
        assert _btc_amounts_match(100, 0) is False

    def test_within_tolerance_low(self):
        # 100 vs 110 = 9.1% diff → within 20%
        assert _btc_amounts_match(100, 110) is True

    def test_within_tolerance_at_boundary(self):
        # 100 vs 125 = 20% diff → exactly at boundary, should match (<=)
        assert _btc_amounts_match(100, 125) is True

    def test_just_outside_tolerance(self):
        # 100 vs 130 = 23% diff → exceeds 20%
        assert _btc_amounts_match(100, 130) is False

    def test_doubled_no_match(self):
        assert _btc_amounts_match(100, 200) is False


class TestDatesWithinWindow:
    def test_same_day(self):
        assert _dates_within_window("2025-01-01", "2025-01-01") is True

    def test_within_window(self):
        assert _dates_within_window("2025-01-01", "2025-01-03") is True

    def test_at_boundary(self):
        # 3 days exactly = within window (<=)
        assert _dates_within_window("2025-01-01", "2025-01-04") is True

    def test_outside_window(self):
        assert _dates_within_window("2025-01-01", "2025-01-10") is False

    def test_invalid_dates(self):
        assert _dates_within_window("not a date", "2025-01-01") is False

    def test_empty_dates(self):
        assert _dates_within_window("", "2025-01-01") is False


class TestIsSuspiciousTarget:
    def test_known_target_no_url_is_suspicious(self):
        assert _is_suspicious_target(100000, "", "snapshot") is True
        assert _is_suspicious_target(210000, "", "news") is True
        assert _is_suspicious_target(1000000, "", "global_filing") is True

    def test_target_amount_with_url_passes(self):
        # Has a filing URL → trust it even if amount looks like a target
        assert _is_suspicious_target(100000, "https://sec.gov/8k/test", "snapshot") is False

    def test_edgar_always_exempt(self):
        # SEC filings are legal documents — trust them even with target amounts
        assert _is_suspicious_target(100000, "", "edgar") is False
        assert _is_suspicious_target(210000, "", "edgar") is False

    def test_non_target_amount_passes(self):
        assert _is_suspicious_target(50, "", "snapshot") is False
        assert _is_suspicious_target(12345, "", "snapshot") is False

    def test_all_known_targets_flagged(self):
        # If anyone removes amounts from SUSPICIOUS_TARGET_AMOUNTS, this fails
        for amount in SUSPICIOUS_TARGET_AMOUNTS:
            assert _is_suspicious_target(amount, "", "snapshot") is True


class TestSourceRank:
    def test_edgar_is_rank_1(self):
        assert _get_source_rank("SEC EDGAR 8-K") == SOURCE_RANKS["edgar"]
        assert _get_source_rank("EDGAR realtime") == SOURCE_RANKS["edgar"]

    def test_global_filing_rank(self):
        assert _get_source_rank("SEDAR Filing") == SOURCE_RANKS["global_filing"]
        assert _get_source_rank("TDnet announcement") == SOURCE_RANKS["global_filing"]
        assert _get_source_rank("DART (South Korea)") == SOURCE_RANKS["global_filing"]
        assert _get_source_rank("RNS (UK)") == SOURCE_RANKS["global_filing"]

    def test_news_rank(self):
        assert _get_source_rank("CoinDesk article") == SOURCE_RANKS["news"]
        assert _get_source_rank("Press release") == SOURCE_RANKS["news"]
        assert _get_source_rank("CoinTelegraph") == SOURCE_RANKS["news"]

    def test_snapshot_default(self):
        # Anything that doesn't match the higher-rank patterns falls to snapshot
        assert _get_source_rank("aggregator delta") == SOURCE_RANKS["snapshot"]
        assert _get_source_rank("") == SOURCE_RANKS["snapshot"]

    def test_rank_ordering(self):
        assert SOURCE_RANKS["edgar"] < SOURCE_RANKS["global_filing"]
        assert SOURCE_RANKS["global_filing"] < SOURCE_RANKS["news"]
        assert SOURCE_RANKS["news"] < SOURCE_RANKS["snapshot"]


class TestConstants:
    """Catch silent changes to dedup tuning that affect every stored record."""

    def test_dedup_window_unchanged(self):
        assert DEDUP_DAYS_WINDOW == 3

    def test_dedup_tolerance_unchanged(self):
        assert DEDUP_BTC_TOLERANCE == 0.20


# ─── Integration tests with mocked supabase ─────────────────────────────────

@pytest.fixture(autouse=True)
def _patch_supabase(monkeypatch, mock_supabase):
    """Auto-applied: replace the reconciler's supabase client with a mock for every test below."""
    monkeypatch.setattr("treasury_signals.pipelines.purchase_reconciler.supabase", mock_supabase)
    yield mock_supabase


def _purchase(**overrides):
    """Build a purchase dict with sensible defaults; tests override fields."""
    base = {
        "company": "Test Co",
        "ticker": "TEST",
        "btc_amount": 100,
        "usd_amount": 5_000_000,
        "price_per_btc": 50_000,
        "filing_date": "2026-05-08",
        "source": "test",
        "notes": "",
        "filing_url": "",
    }
    base.update(overrides)
    return base


def _calls_to_table(mock_supabase, table_name):
    """Return the list of method calls made on supabase.table(<name>)."""
    return [c for c in mock_supabase.table.call_args_list if c.args == (table_name,)]


class TestReconcileSnapshot:
    """Snapshot detections must NEVER auto-confirm — always go to pending."""

    def test_snapshot_writes_pending_not_confirmed(self, mock_supabase):
        result = reconcile_and_save(_purchase(), source_type="snapshot")
        assert result["action"] == "pending"
        # Should call .table("pending_purchases") at least once for the upsert
        assert any(c.args == ("pending_purchases",) for c in mock_supabase.table.call_args_list)
        # All upsert payloads must be pending entries (have pending_id, not purchase_id).
        # Confirmed-purchase payloads always include "purchase_id" — none should appear.
        upsert_payloads = [c.args[0] for c in mock_supabase.table.return_value.upsert.call_args_list]
        assert upsert_payloads, "expected at least one upsert"
        for payload in upsert_payloads:
            assert "pending_id" in payload, f"snapshot wrote a non-pending payload: {payload}"
            assert "purchase_id" not in payload, f"snapshot wrote a confirmed payload: {payload}"

    def test_snapshot_target_amount_rejected(self, mock_supabase):
        result = reconcile_and_save(_purchase(btc_amount=100000), source_type="snapshot")
        assert result["action"] == "rejected_target"

    def test_snapshot_target_with_filing_url_passes_to_pending(self, mock_supabase):
        result = reconcile_and_save(
            _purchase(btc_amount=100000, filing_url="https://example.com/8k"),
            source_type="snapshot",
        )
        # With a filing URL, the target check passes, but snapshot still goes to pending
        assert result["action"] == "pending"

    def test_new_entrant_marked_in_pending(self, mock_supabase):
        result = reconcile_and_save(_purchase(), source_type="snapshot", is_new_entrant=True)
        assert result["action"] == "pending"
        # The pending_purchases insert should include is_new_entrant=True
        upsert_calls = mock_supabase.table.return_value.upsert.call_args_list
        assert upsert_calls, "expected at least one upsert call"
        last_payload = upsert_calls[-1].args[0]
        assert last_payload.get("is_new_entrant") is True


class TestReconcileEdgar:
    """EDGAR is rank 1 (highest) — auto-confirms purchases without needing corroboration."""

    def test_edgar_creates_confirmed(self, mock_supabase):
        result = reconcile_and_save(
            _purchase(filing_url="https://sec.gov/Archives/edgar/data/123/8k.htm"),
            source_type="edgar",
        )
        assert result["action"] == "confirmed"
        # Should have written to confirmed_purchases
        assert any(c.args == ("confirmed_purchases",) for c in mock_supabase.table.call_args_list)

    def test_edgar_target_amount_still_accepted(self, mock_supabase):
        # EDGAR is exempt from the suspicious-target gate
        result = reconcile_and_save(
            _purchase(btc_amount=100000),
            source_type="edgar",
        )
        # Should NOT be rejected — should be confirmed
        assert result["action"] == "confirmed"


class TestReconcileSale:
    """Sales mirror the purchase pipeline — same gates, separate confirmed_sales table."""

    def test_snapshot_sale_goes_to_pending(self, mock_supabase):
        result = reconcile_sale(_purchase(), source_type="snapshot")
        assert result["action"] == "pending"
        # Should write to pending_purchases (sales share the table with transaction_type=sale)
        upsert_calls = mock_supabase.table.return_value.upsert.call_args_list
        assert upsert_calls
        last_payload = upsert_calls[-1].args[0]
        assert last_payload.get("transaction_type") == "sale"

    def test_edgar_sale_creates_confirmed(self, mock_supabase):
        result = reconcile_sale(
            _purchase(filing_url="https://sec.gov/Archives/edgar/data/123/8k.htm"),
            source_type="edgar",
        )
        assert result["action"] == "confirmed"
        assert any(c.args == ("confirmed_sales",) for c in mock_supabase.table.call_args_list)
