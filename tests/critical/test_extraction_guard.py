"""
Critical-path regression tests for the extraction sanity guard.

This guard is the last gate before an extracted BTC transaction amount reaches a
paying customer (Telegram alert) or the confirmed_purchases/sales ledger. The
canonical failure it must stop is the "MSTR SOLD 843,738 BTC" misparse — a
holdings total announced as a transaction. Pure functions, no DB.
"""
from treasury_signals.pipelines import extraction_guard as g
from treasury_signals.pipelines.extraction_guard import validate_transaction


class TestAbsoluteBounds:
    def test_zero_amount_is_ok_noop(self):
        v = validate_transaction("purchase", 0, current_holdings=1000)
        assert v.ok and v.code == "no_amount"

    def test_amount_at_or_above_total_supply_rejected(self):
        v = validate_transaction("purchase", g.MAX_BTC_SUPPLY, current_holdings=None)
        assert not v.ok and v.code == "exceeds_supply"

    def test_six_figure_single_transaction_rejected_even_without_holdings(self):
        # The holdings-total-as-transaction case with no known holdings: absolute
        # ceiling still catches it (843,738 is a holdings total, never one buy).
        v = validate_transaction("purchase", 843_738, current_holdings=0)
        assert not v.ok and v.code == "implausible_txn"

    def test_large_but_plausible_new_entrant_buy_passes(self):
        # A genuine 30k-BTC debut with no prior holdings must NOT be suppressed.
        v = validate_transaction("purchase", 30_000, current_holdings=0)
        assert v.ok


class TestSaleExceedsHoldings:
    def test_sale_far_above_holdings_rejected(self):
        # The literal "sold 99% / sold more than held" guard.
        v = validate_transaction("sale", 50_000, current_holdings=15_000)
        assert not v.ok and v.code == "sale_exceeds_holdings"

    def test_full_liquidation_within_tolerance_passes(self):
        # Selling exactly what you hold is a real, important event — allow it.
        v = validate_transaction("sale", 15_000, current_holdings=15_000)
        assert v.ok

    def test_small_overage_within_tolerance_passes(self):
        # Holdings data can lag the filing by a sync cycle; 5% tolerance.
        v = validate_transaction("sale", 15_500, current_holdings=15_000)
        assert v.ok


class TestPurchaseExceedsHoldings:
    def test_purchase_over_3x_holdings_rejected(self):
        # "aims to acquire 100,000 BTC" parsed as a buy against 5k holdings.
        v = validate_transaction("purchase", 100_000, current_holdings=5_000)
        # exceeds the absolute single-txn ceiling first — still rejected.
        assert not v.ok

    def test_purchase_just_over_3x_rejected_via_holdings_rule(self):
        # Below the absolute ceiling, so the relative 3x rule must catch it.
        v = validate_transaction("purchase", 31_000, current_holdings=10_000)
        assert not v.ok and v.code == "purchase_exceeds_holdings"

    def test_aggressive_but_sane_accumulation_passes(self):
        # Doubling holdings in one buy is aggressive but real (e.g. MSTR-style).
        v = validate_transaction("purchase", 18_000, current_holdings=10_000)
        assert v.ok


class TestUnknownHoldings:
    def test_relative_checks_skipped_when_holdings_unknown(self):
        # Holdings unknown → only absolute bounds apply; a normal-size buy passes.
        v = validate_transaction("sale", 4_000, current_holdings=None)
        assert v.ok

    def test_bool_protocol(self):
        # Callers rely on `if not guard:` — verify __bool__ tracks .ok.
        assert bool(validate_transaction("purchase", 100, 1000)) is True
        assert bool(validate_transaction("sale", 99_999, 100)) is False
