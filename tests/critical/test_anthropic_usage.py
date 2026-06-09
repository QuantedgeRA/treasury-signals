"""
Critical-path tests for Anthropic spend estimation.

estimate_cost + usage_from_response are pure (no DB). They underpin the spend
monitor that fires the daily cost-cap admin alert, so the price math and the
response parsing must be right. record_usage's DB path is best-effort/fail-open
and exercised in integration, not here.
"""
from treasury_signals.pipelines import anthropic_usage as u


class TestEstimateCost:
    def test_sonnet_pricing(self):
        # 1M in + 1M out at Sonnet $3/$15 = $18.00
        assert u.estimate_cost("claude-sonnet-4-5-20250929", 1_000_000, 1_000_000) == 18.0

    def test_haiku_pricing(self):
        # Haiku $0.80/$4.00; 'haiku' must win over the generic default.
        assert u.estimate_cost("claude-haiku-4-5", 1_000_000, 1_000_000) == 4.80

    def test_opus_pricing(self):
        assert u.estimate_cost("claude-opus-4-8", 1_000_000, 1_000_000) == 90.0

    def test_unknown_model_assumes_sonnet_default(self):
        assert u.estimate_cost("some-future-model", 1_000_000, 0) == 3.0

    def test_small_token_counts_scale_linearly(self):
        # 12,000 in + 800 out on Sonnet
        cost = u.estimate_cost("claude-sonnet-4-20250514", 12_000, 800)
        assert round(cost, 6) == round((12_000 / 1e6) * 3.0 + (800 / 1e6) * 15.0, 6)

    def test_zero_tokens_zero_cost(self):
        assert u.estimate_cost("claude-sonnet", 0, 0) == 0.0


class TestUsageFromResponse:
    def test_extracts_token_counts(self):
        body = {"usage": {"input_tokens": 1234, "output_tokens": 56}, "content": []}
        assert u.usage_from_response(body) == (1234, 56)

    def test_missing_usage_returns_zeros(self):
        assert u.usage_from_response({"content": []}) == (0, 0)

    def test_none_safe(self):
        assert u.usage_from_response(None) == (0, 0)

    def test_garbage_values_coerce_to_zero(self):
        assert u.usage_from_response({"usage": {"input_tokens": None, "output_tokens": "x"}}) == (0, 0)
