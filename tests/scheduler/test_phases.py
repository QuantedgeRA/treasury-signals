"""Tests for treasury_signals.scheduler.phases.

Each phase function takes a ScanState, calls some external function(s),
and (sometimes) mutates state. These tests verify three properties:
  1. State propagation — phases that produce data write to the right
     state fields with the right values.
  2. Argument plumbing — accounts/scan_number/morning flow into the
     right downstream calls.
  3. Error swallow — a thrown exception in a dependency does NOT
     propagate out of the phase (verbatim behavior preservation from
     the pre-refactor code that wrapped each phase in try/except).

Phases call helpers in scheduler.helpers; we mock them at the phases
module's namespace (the phase-level import binding, not the source
module) so tests don't accidentally hit network/DB.
"""

import pytest
from unittest.mock import MagicMock

from treasury_signals.scheduler.state import ScanState
from treasury_signals.scheduler import phases


# ─── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def state():
    """Default ScanState — non-morning, one fake account."""
    return ScanState(scan_number=1, morning=False, accounts=[{'username': 'test_user'}])


@pytest.fixture
def morning_state():
    """ScanState with morning=True for morning-only branches."""
    return ScanState(scan_number=1, morning=True, accounts=[{'username': 'test_user'}])


# ─── Phase 1 — tweet fetch ─────────────────────────────────────────────────

class TestPhase1Tweets:
    def test_populates_state_with_counts(self, monkeypatch, state):
        monkeypatch.setattr(phases, 'scan_all_accounts', lambda accs: (5, 2))
        phases.phase_1_tweets(state)
        assert state.tweets_new == 5
        assert state.tweets_skipped == 2

    def test_passes_accounts_through(self, monkeypatch, state):
        captured = []
        def fake(accs):
            captured.append(accs)
            return (0, 0)
        monkeypatch.setattr(phases, 'scan_all_accounts', fake)
        phases.phase_1_tweets(state)
        assert captured[0] == state.accounts

    def test_zero_results(self, monkeypatch, state):
        monkeypatch.setattr(phases, 'scan_all_accounts', lambda accs: (0, 0))
        phases.phase_1_tweets(state)
        assert state.tweets_new == 0
        assert state.tweets_skipped == 0


# ─── Phase 2 — classify ────────────────────────────────────────────────────

class TestPhase2Classify:
    def test_populates_signals_and_alerts(self, monkeypatch, state):
        signals = [{'author': 'saylor', 'score': 80}]
        monkeypatch.setattr(phases, 'process_and_alert', lambda: (signals, 1))
        phases.phase_2_classify(state)
        assert state.signals == signals
        assert state.alerts_sent == 1

    def test_empty_signals(self, monkeypatch, state):
        monkeypatch.setattr(phases, 'process_and_alert', lambda: ([], 0))
        phases.phase_2_classify(state)
        assert state.signals == []
        assert state.alerts_sent == 0


# ─── Phase 3 — STRC ────────────────────────────────────────────────────────

class TestPhase3Strc:
    def test_invokes_check_strc_volume(self, monkeypatch, state):
        called = []
        monkeypatch.setattr(phases, 'check_strc_volume', lambda: called.append(True))
        phases.phase_3_strc(state)
        assert called == [True]


# ─── Phase 4 — EDGAR realtime ──────────────────────────────────────────────

class TestPhase4Edgar:
    def test_invokes_check_edgar_realtime(self, monkeypatch, state):
        captured = []
        def fake(days_back=1):
            captured.append(days_back)
            return {'new_filings': 0}
        monkeypatch.setattr(phases, 'check_edgar_realtime', fake)
        phases.phase_4_edgar(state)
        assert captured == [1]

    def test_swallows_edgar_exception(self, monkeypatch, state):
        def raises(days_back=1):
            raise RuntimeError('EDGAR down')
        monkeypatch.setattr(phases, 'check_edgar_realtime', raises)
        # Should not raise — phase wraps in try/except
        phases.phase_4_edgar(state)


# ─── Phase 5 — correlation engine + pattern matching ───────────────────────

class TestPhase5Correlation:
    def test_populates_state_fields(self, monkeypatch, state):
        risk = {'fear_greed_value': 60, 'btc_7d_change': 5.5, 'btc_price': 70000}
        monkeypatch.setattr(
            'treasury_signals.scanners.market_intelligence.get_risk_dashboard',
            lambda: risk,
        )
        monkeypatch.setattr(
            phases, 'check_correlation',
            lambda: {'market_score': 75, 'total_streams': 4, 'alert_level': 'HIGH'},
        )
        monkeypatch.setattr(phases, 'get_strc_volume_data', lambda: {'volume_ratio': 1.8})

        # Mock engine.update_market_context (no-op)
        monkeypatch.setattr(phases.engine, 'update_market_context', lambda **kw: None)

        # Mock pattern_engine
        mock_pe = MagicMock()
        mock_pe.match_current_conditions.return_value = {
            'score': 50, 'matched_count': 2, 'total_patterns': 5,
            'matching_patterns': [], 'narrative': '',
        }
        monkeypatch.setattr(phases, 'pattern_engine', mock_pe)

        phases.phase_5_correlation(state)

        assert state.fg_value == 60
        assert state.btc_weekly == 5.5
        assert state.correlation['market_score'] == 75
        assert state.pattern_match['score'] == 50

    def test_falls_back_on_market_intelligence_failure(self, monkeypatch, state):
        # When market intelligence fetch fails, phase should still produce
        # a correlation result and keep state.fg_value/btc_weekly at defaults.
        def raises():
            raise RuntimeError('API down')
        monkeypatch.setattr(
            'treasury_signals.scanners.market_intelligence.get_risk_dashboard',
            raises,
        )
        monkeypatch.setattr(
            phases, 'check_correlation',
            lambda: {'market_score': 0, 'total_streams': 0, 'alert_level': 'NONE'},
        )
        monkeypatch.setattr(phases, 'get_strc_volume_data', lambda: None)

        mock_pe = MagicMock()
        mock_pe.match_current_conditions.return_value = {
            'score': 0, 'matched_count': 0, 'total_patterns': 0,
            'matching_patterns': [], 'narrative': '',
        }
        monkeypatch.setattr(phases, 'pattern_engine', mock_pe)
        monkeypatch.setattr(phases.engine, 'update_market_context', lambda **kw: None)

        phases.phase_5_correlation(state)

        # Defaults from ScanState preserved
        assert state.fg_value == 50
        assert state.btc_weekly == 0


# ─── Phase 6 / 7 / 9 / 10 — invocation tests (no state mutation) ───────────

class TestSimplePhases:
    def test_phase_6_invokes_send_daily_email(self, monkeypatch, state):
        called = []
        monkeypatch.setattr(phases, 'send_daily_email', lambda: called.append(True))
        phases.phase_6_email(state)
        assert called == [True]

    def test_phase_7_invokes_send_daily_leaderboard(self, monkeypatch, state):
        called = []
        monkeypatch.setattr(phases, 'send_daily_leaderboard', lambda: called.append(True))
        phases.phase_7_leaderboard(state)
        assert called == [True]

    def test_phase_9_invokes_scan_regulatory(self, monkeypatch, state):
        called = []
        monkeypatch.setattr(phases, 'scan_regulatory', lambda: called.append(True))
        phases.phase_9_regulatory(state)
        assert called == [True]

    def test_phase_10_pings_url(self, monkeypatch, state):
        captured = []
        mock_resp = MagicMock(status_code=200)
        def fake_get(url, timeout):
            captured.append(url)
            return mock_resp
        monkeypatch.setattr(phases.req, 'get', fake_get)
        phases.phase_10_dashboard_ping(state)
        assert len(captured) == 1
        assert 'streamlit' in captured[0].lower()

    def test_phase_10_swallows_http_failure(self, monkeypatch, state):
        def raises(url, timeout):
            raise RuntimeError('network down')
        monkeypatch.setattr(phases.req, 'get', raises)
        # Should not raise
        phases.phase_10_dashboard_ping(state)


# ─── Phase 8 — purchase detection ──────────────────────────────────────────

class TestPhase8PurchaseDetection:
    def test_populates_state_detected_when_purchases_found(self, monkeypatch, state):
        detected = [
            {'company': 'MSTR', 'btc_amount': 1000, 'ticker': 'MSTR', 'was_predicted': False},
        ]
        monkeypatch.setattr(phases, 'scan_news_for_purchases', lambda: [])
        monkeypatch.setattr(phases, 'detect_new_purchases', lambda: detected)
        monkeypatch.setattr(phases, 'log_detected_purchases', lambda d: None)
        monkeypatch.setattr(phases, 'format_purchase_telegram', lambda d: 'msg')
        monkeypatch.setattr(phases, 'send_to_paid', lambda m: None)
        monkeypatch.setattr(phases, 'send_to_free', lambda m: None)
        monkeypatch.setattr(phases, 'promote_pending_purchases', lambda: 0)
        monkeypatch.setattr(phases, 'promote_pending_sales', lambda: 0)
        monkeypatch.setattr(phases, 'expire_stale_pending', lambda: 0)
        monkeypatch.setattr(phases, 'get_reconciler_stats', lambda: {
            'confirmed_total': 0, 'pending_buys': 0, 'pending_sales': 0,
            'promoted_count': 0, 'discarded_count': 0,
        })
        # Stub correlation engine call
        monkeypatch.setattr(phases.engine, 'add_news_signal', lambda **kw: None)
        # Stub narrator
        mock_n = MagicMock()
        mock_n.analyze_purchase.return_value = None
        monkeypatch.setattr(phases, 'narrator', mock_n)

        phases.phase_8_purchase_detection(state)
        assert state.detected == detected

    def test_empty_detected_when_no_purchases(self, monkeypatch, state):
        monkeypatch.setattr(phases, 'scan_news_for_purchases', lambda: [])
        monkeypatch.setattr(phases, 'detect_new_purchases', lambda: [])
        monkeypatch.setattr(phases, 'promote_pending_purchases', lambda: 0)
        monkeypatch.setattr(phases, 'promote_pending_sales', lambda: 0)
        monkeypatch.setattr(phases, 'expire_stale_pending', lambda: 0)
        monkeypatch.setattr(phases, 'get_reconciler_stats', lambda: {
            'confirmed_total': 0, 'pending_buys': 0, 'pending_sales': 0,
            'promoted_count': 0, 'discarded_count': 0,
        })
        phases.phase_8_purchase_detection(state)
        assert state.detected == []

    def test_expire_stale_only_runs_morning(self, monkeypatch, state, morning_state):
        # state.morning = False — expire should NOT be called
        called = []
        monkeypatch.setattr(phases, 'scan_news_for_purchases', lambda: [])
        monkeypatch.setattr(phases, 'detect_new_purchases', lambda: [])
        monkeypatch.setattr(phases, 'promote_pending_purchases', lambda: 0)
        monkeypatch.setattr(phases, 'promote_pending_sales', lambda: 0)
        monkeypatch.setattr(phases, 'expire_stale_pending', lambda: called.append('expired') or 0)
        monkeypatch.setattr(phases, 'get_reconciler_stats', lambda: {
            'confirmed_total': 0, 'pending_buys': 0, 'pending_sales': 0,
            'promoted_count': 0, 'discarded_count': 0,
        })
        phases.phase_8_purchase_detection(state)
        assert called == [], "expire_stale_pending should not run on non-morning scan"

        # Reset and run with morning=True
        called.clear()
        phases.phase_8_purchase_detection(morning_state)
        assert called == ['expired'], "expire_stale_pending should run on morning scan"
