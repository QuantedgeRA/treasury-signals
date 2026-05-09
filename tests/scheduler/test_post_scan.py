"""Tests for treasury_signals.scheduler.post_scan.

Each function corresponds to one section of the previous post-scan inline
block in main.py. Tests focus on:
  1. Morning gating — functions like run_daily_only_tasks and
     run_heavy_maintenance must no-op when state.morning is False.
  2. State usage — run_watchlist_alerts must read from state.signals/
     detected; send_scan_summary_log must extract from state.correlation
     safely (no KeyError on missing fields).
  3. Error swallow — failures in dependencies don't crash the scan.
"""

import pytest
from unittest.mock import MagicMock

from treasury_signals.scheduler.state import ScanState
from treasury_signals.scheduler import post_scan


@pytest.fixture
def state():
    return ScanState(scan_number=1, morning=False, accounts=[])


@pytest.fixture
def morning_state():
    return ScanState(scan_number=1, morning=True, accounts=[])


# ─── save_freshness_snapshot ───────────────────────────────────────────────

class TestSaveFreshnessSnapshot:
    def test_calls_save_to_supabase(self, monkeypatch):
        called = []
        mock_freshness = MagicMock()
        mock_freshness.save_to_supabase = lambda db: called.append('saved')
        mock_freshness.get_overall_health.return_value = {
            'emoji': '🟢', 'health': 'healthy', 'message': 'all good',
        }
        monkeypatch.setattr(post_scan, 'freshness', mock_freshness)
        post_scan.save_freshness_snapshot()
        assert called == ['saved']

    def test_swallows_save_error(self, monkeypatch):
        # If save_to_supabase raises, function must still log health, not crash
        mock_freshness = MagicMock()
        mock_freshness.save_to_supabase.side_effect = RuntimeError('DB down')
        mock_freshness.get_overall_health.return_value = {
            'emoji': '🔴', 'health': 'critical', 'message': 'broken',
        }
        monkeypatch.setattr(post_scan, 'freshness', mock_freshness)
        # Should not raise
        post_scan.save_freshness_snapshot()


# ─── run_daily_only_tasks (morning gate) ───────────────────────────────────

class TestRunDailyOnlyTasks:
    def test_no_op_when_not_morning(self, monkeypatch, state):
        called = []
        mock_fe = MagicMock()
        mock_fe.learn = lambda: called.append('learn')
        monkeypatch.setattr(post_scan, 'feedback_engine', mock_fe)
        mock_pred = MagicMock()
        mock_pred.analyze = lambda: called.append('analyze')
        monkeypatch.setattr(post_scan, 'predictor', mock_pred)

        post_scan.run_daily_only_tasks(state)  # state.morning = False
        assert called == [], "no learning tasks should run outside morning"

    def test_runs_when_morning(self, monkeypatch, morning_state):
        called = []
        mock_fe = MagicMock()
        mock_fe.learn = lambda: called.append('learn')
        mock_fe.load_from_db = lambda: called.append('load')
        mock_fe.get_learning_report.return_value = "Some learning data found"
        monkeypatch.setattr(post_scan, 'feedback_engine', mock_fe)

        mock_pred = MagicMock()
        mock_pred.analyze = lambda: called.append('analyze')
        monkeypatch.setattr(post_scan, 'predictor', mock_pred)

        post_scan.run_daily_only_tasks(morning_state)
        assert 'learn' in called
        assert 'analyze' in called

    def test_swallows_feedback_loop_failure(self, monkeypatch, morning_state):
        mock_fe = MagicMock()
        mock_fe.learn.side_effect = RuntimeError('learn failed')
        monkeypatch.setattr(post_scan, 'feedback_engine', mock_fe)

        called_predictor = []
        mock_pred = MagicMock()
        mock_pred.analyze = lambda: called_predictor.append(True)
        monkeypatch.setattr(post_scan, 'predictor', mock_pred)

        # Predictor should still run even if feedback_engine fails
        post_scan.run_daily_only_tasks(morning_state)
        assert called_predictor == [True], "predictor must run even if feedback_engine throws"


# ─── run_heavy_maintenance (morning gate) ──────────────────────────────────

class TestRunHeavyMaintenance:
    def test_no_op_when_not_morning(self, monkeypatch, state):
        called = []
        monkeypatch.setattr(post_scan, 'update_shares', lambda: called.append('shares'))
        monkeypatch.setattr(post_scan, 'validate_all_tickers', lambda: called.append('tickers'))
        monkeypatch.setattr(post_scan, 'sync_shares_outstanding', lambda limit=50: called.append('sync'))
        post_scan.run_heavy_maintenance(state)
        assert called == [], "no maintenance should run outside morning"

    def test_runs_all_three_when_morning(self, monkeypatch, morning_state):
        called = []
        monkeypatch.setattr(post_scan, 'update_shares', lambda: called.append('shares'))
        monkeypatch.setattr(post_scan, 'validate_all_tickers', lambda: called.append('tickers'))
        monkeypatch.setattr(post_scan, 'sync_shares_outstanding',
                            lambda limit=50: called.append(f'sync({limit})') or {'updated': 0})
        post_scan.run_heavy_maintenance(morning_state)
        assert 'shares' in called
        assert 'tickers' in called
        assert 'sync(50)' in called  # confirms limit param wiring


# ─── run_watchlist_alerts (uses state.signals + state.detected) ────────────

class TestRunWatchlistAlerts:
    def test_passes_state_signals_and_detected_to_activity_check(self, monkeypatch, state):
        state.signals = [{'company': 'MSTR', 'score': 80}]
        state.detected = [{'company': 'MARA', 'btc_amount': 100}]
        captured = {}

        mock_subs = MagicMock()
        mock_subs.get_active_subscribers.return_value = [
            {'name': 'TestUser', 'watchlist': '["MSTR"]', 'telegram_chat_id': None},
        ]
        monkeypatch.setattr(post_scan, 'subscribers', mock_subs)

        def capture(watchlist, signals, purchases):
            captured['signals'] = signals
            captured['purchases'] = purchases
            return []  # no high-priority items
        monkeypatch.setattr(post_scan, 'get_watchlist_activity', capture)

        post_scan.run_watchlist_alerts(state)
        assert captured['signals'] == state.signals
        assert captured['purchases'] == state.detected

    def test_skips_subscribers_with_empty_watchlist(self, monkeypatch, state):
        called = []
        mock_subs = MagicMock()
        mock_subs.get_active_subscribers.return_value = [
            {'name': 'NoWatch', 'watchlist': []},
            {'name': 'EmptyStr', 'watchlist': ''},
        ]
        monkeypatch.setattr(post_scan, 'subscribers', mock_subs)
        monkeypatch.setattr(post_scan, 'get_watchlist_activity',
                            lambda **kw: called.append('activity_checked') or [])
        post_scan.run_watchlist_alerts(state)
        assert called == [], "should skip subscribers with empty watchlists"

    def test_swallows_subscriber_fetch_error(self, monkeypatch, state):
        mock_subs = MagicMock()
        mock_subs.get_active_subscribers.side_effect = RuntimeError('DB down')
        monkeypatch.setattr(post_scan, 'subscribers', mock_subs)
        # Should not raise
        post_scan.run_watchlist_alerts(state)


# ─── send_scan_summary_log (state.correlation safety) ──────────────────────

class TestSendScanSummaryLog:
    def test_extracts_correlation_fields(self, monkeypatch, state):
        state.correlation = {'market_score': 65, 'total_streams': 3, 'alert_level': 'MEDIUM'}
        state.tweets_new = 10
        state.signals = [1, 2, 3]
        captured = []
        monkeypatch.setattr(post_scan, 'send_scan_summary',
                            lambda *a: captured.append(a))
        post_scan.send_scan_summary_log(state, accounts=[{'u': 'a'}, {'u': 'b'}])
        # Signature: (scan_number, accounts_count, tweets_new, signals_count)
        assert captured[0] == (1, 2, 10, 3)

    def test_handles_empty_correlation_safely(self, monkeypatch, state):
        # If correlation phase failed and produced empty dict, summary
        # still must not crash on missing keys.
        state.correlation = {}
        state.tweets_new = 0
        state.signals = []
        captured = []
        monkeypatch.setattr(post_scan, 'send_scan_summary',
                            lambda *a: captured.append(a))
        # Must not raise
        post_scan.send_scan_summary_log(state, accounts=[])
        assert captured[0] == (1, 0, 0, 0)


# ─── run_entity_sync — verify call order ───────────────────────────────────

class TestRunEntitySync:
    def test_calls_three_steps_in_order(self, monkeypatch):
        order = []
        monkeypatch.setattr(post_scan, 'snapshot_primary_data', lambda: order.append('snapshot'))
        mock_sync = MagicMock()
        mock_sync.run = lambda: order.append('sync')
        monkeypatch.setattr(post_scan, 'treasury_sync', mock_sync)
        monkeypatch.setattr(post_scan, 'protect_primary_data', lambda: order.append('protect'))
        post_scan.run_entity_sync()
        # Strict order: snapshot before sync before protect
        assert order == ['snapshot', 'sync', 'protect']

    def test_protect_runs_even_if_sync_fails(self, monkeypatch):
        order = []
        monkeypatch.setattr(post_scan, 'snapshot_primary_data', lambda: order.append('snapshot'))
        mock_sync = MagicMock()
        mock_sync.run.side_effect = RuntimeError('sync failed')
        monkeypatch.setattr(post_scan, 'treasury_sync', mock_sync)
        monkeypatch.setattr(post_scan, 'protect_primary_data', lambda: order.append('protect'))
        post_scan.run_entity_sync()
        # snapshot runs, sync raises but is swallowed, protect still runs
        assert order == ['snapshot', 'protect']
