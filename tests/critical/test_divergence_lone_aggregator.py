"""
Critical-path regression tests for the laggy-aggregator divergence down-weight.

A scraped aggregator (CoinGecko/DeFiLlama) lagging behind a primary disclosure
must NOT raise a divergence alert: the trust hierarchy already resolved to the
primary value, so the alert is unactionable noise. This locks in the 2026-06 fix
that cleared the 37-name CoinGecko-lag backlog — while still alerting when two
genuine primaries disagree. _compute_divergence is pure (operates on crafted
Observation lists), no DB.
"""
from datetime import datetime, timezone

from treasury_signals.pipelines import btc_holdings_reconciler as r
from treasury_signals.pipelines.btc_holdings_reconciler import Observation


def _obs(source, value):
    return Observation(
        ticker="TEST",
        source=source,
        btc_value=float(value),
        observed_at=datetime.now(timezone.utc),  # fresh → full trust
    )


class TestLoneAggregatorSuppressed:
    def test_single_primary_vs_lagging_coingecko_not_divergent(self):
        # EDGAR (primary, trust 100) says 16,492; CoinGecko (trust 40) lags at
        # 182. Only one primary → nothing to diverge against → no alert.
        spread_btc, spread_pct, diverging = r._compute_divergence(
            [_obs("edgar_8k", 16_492), _obs("coingecko", 182)]
        )
        assert spread_btc == 0.0
        assert diverging == []

    def test_primary_cluster_agrees_aggregator_lags_not_divergent(self):
        # Two primaries agree (16,492 vs 16,500); CoinGecko lags at 182. Judging
        # on the primary cluster, they're effectively identical → no alert.
        spread_btc, spread_pct, diverging = r._compute_divergence(
            [_obs("edgar_8k", 16_492), _obs("press_release", 16_500), _obs("coingecko", 182)]
        )
        # spread is the tiny primary-vs-primary gap, not the huge aggregator gap
        assert spread_btc == 8.0
        assert "coingecko" not in diverging


class TestRealDivergenceStillFires:
    def test_two_primaries_disagree_is_divergent(self):
        # EDGAR says 16,492, a press release says 10,000 — a real primary-vs-
        # primary conflict that an operator must investigate. Must still flag.
        spread_btc, spread_pct, diverging = r._compute_divergence(
            [_obs("edgar_8k", 16_492), _obs("press_release", 10_000)]
        )
        assert spread_btc == 6_492.0
        assert r._is_divergent(spread_btc, spread_pct) is True

    def test_aggregator_only_pair_near_trust_floor_stays_quiet(self):
        # No primary source — only CoinGecko (trust 40) and DeFiLlama (trust 30,
        # the exact DIVERGENCE_MIN_TRUST floor). Any staleness nudges DeFiLlama
        # just below the floor, leaving a single qualifying aggregator → no
        # alert. Aggregator-only data is intentionally low-confidence and should
        # not page an operator; the resolved value just tracks the higher-trust
        # aggregator. Locks in that we don't manufacture primary-less noise.
        spread_btc, spread_pct, diverging = r._compute_divergence(
            [_obs("coingecko", 1_000), _obs("defillama", 5_000)]
        )
        assert spread_btc == 0.0
        assert diverging == []

    def test_primary_present_with_aggregators_judges_on_primaries(self):
        # Sanity: with a primary in the mix, the laggy set is dropped and the
        # (single) primary leaves nothing to diverge against — no alert — even
        # though two aggregators are wildly apart from it and each other.
        spread_btc, spread_pct, diverging = r._compute_divergence(
            [_obs("edgar_8k", 16_492), _obs("coingecko", 1_000), _obs("defillama", 5_000)]
        )
        assert spread_btc == 0.0
        assert diverging == []
