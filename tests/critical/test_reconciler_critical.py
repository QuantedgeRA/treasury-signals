"""
Critical-path regression tests for the btc_holdings reconciler resolution.

Locks in: (1) the trust hierarchy picks the highest-trust source, (2) the
manual_override divergence-SUPPRESSION fix (a human override must not keep
re-raising divergence alerts against the now-known-wrong aggregator), (3) a
single qualifying source isn't reported as divergent. resolve_ticker reads
observations via supabase, so we monkeypatch the fetch with crafted rows — no DB.
"""
from datetime import datetime, timezone

import pytest

from treasury_signals.pipelines import btc_holdings_reconciler as r
from treasury_signals.pipelines.btc_holdings_reconciler import Observation


def _obs(source, value):
    return Observation(
        ticker="TEST",
        source=source,
        btc_value=float(value),
        observed_at=datetime.now(timezone.utc),  # fresh → full trust, no staleness penalty
    )


@pytest.fixture
def patch_obs(monkeypatch):
    """Make resolve_ticker see a crafted observation set."""
    def _set(observations):
        monkeypatch.setattr(r, "_fetch_observations_for_ticker", lambda ticker: observations)
    return _set


class TestResolution:
    def test_highest_trust_source_wins(self, patch_obs):
        # bitcointreasuries (trust 60) outranks coingecko (trust 40).
        patch_obs([_obs("coingecko", 100), _obs("bitcointreasuries", 200)])
        res = r.resolve_ticker("TEST")
        assert res.resolved_value == 200
        assert res.resolved_source == "bitcointreasuries"

    def test_two_diverging_sources_flag_divergent(self, patch_obs):
        patch_obs([_obs("coingecko", 100), _obs("bitcointreasuries", 200)])
        res = r.resolve_ticker("TEST")
        assert res.is_divergent is True

    def test_single_source_not_divergent(self, patch_obs):
        # Only one qualifying source → nothing to diverge against.
        patch_obs([_obs("bitcointreasuries", 200)])
        res = r.resolve_ticker("TEST")
        assert res.is_divergent is False

    def test_manual_override_wins_and_suppresses_divergence(self, patch_obs):
        # The COIN case: aggregator scraped 182, human override is 16,492. The
        # override must win AND must NOT raise divergence (it would re-open a
        # resolved alert every cycle forever).
        patch_obs([_obs("bitcointreasuries", 182), _obs("manual_override", 16492)])
        res = r.resolve_ticker("TEST")
        assert res.resolved_value == 16492
        assert res.resolved_source == "manual_override"
        assert res.is_divergent is False

    def test_no_observations_returns_none(self, patch_obs):
        # Must return None (caller leaves treasury_companies untouched, not zeroed).
        patch_obs([])
        assert r.resolve_ticker("TEST") is None
