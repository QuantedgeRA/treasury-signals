-- 0029_anthropic_usage.sql
--
-- Anthropic (Claude) spend monitoring. Until now there was ZERO visibility into
-- Claude API cost — not a log aggregate, not a freshness source. This adds a
-- durable per-day-per-model usage aggregate that the extraction callers
-- increment on every API response (token counts come from the response `usage`
-- block), plus an atomic upsert RPC that returns the running daily total so the
-- caller can alert admin once a soft cost cap is crossed.
--
-- The tracker is best-effort + fail-open: if this table/RPC is absent
-- (pre-apply) or errors, extraction proceeds normally and we simply don't
-- record usage. Applying this migration ACTIVATES spend tracking.
--
-- Apply in the Supabase SQL editor (or migration_runner when DATABASE_URL set).

CREATE TABLE IF NOT EXISTS anthropic_usage_daily (
    usage_date    date   NOT NULL,
    model         text   NOT NULL,
    calls         int    NOT NULL DEFAULT 0,
    input_tokens  bigint NOT NULL DEFAULT 0,
    output_tokens bigint NOT NULL DEFAULT 0,
    est_cost_usd  numeric(12,4) NOT NULL DEFAULT 0,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (usage_date, model)
);

-- Service-role only (the worker/crons record usage with the service-role key).
-- RLS on + no policy = no anon/authenticated access; service_role bypasses RLS.
ALTER TABLE anthropic_usage_daily ENABLE ROW LEVEL SECURITY;

-- Atomically fold one API call into the day's aggregate and return the running
-- TOTAL estimated cost across all models for that day (so the caller can decide
-- whether to fire a cost-cap alert).
CREATE OR REPLACE FUNCTION record_anthropic_usage(
    p_date  date,
    p_model text,
    p_input bigint,
    p_output bigint,
    p_cost  numeric
) RETURNS numeric
LANGUAGE plpgsql AS $$
DECLARE
    day_total numeric;
BEGIN
    INSERT INTO anthropic_usage_daily(
        usage_date, model, calls, input_tokens, output_tokens, est_cost_usd, updated_at
    )
    VALUES (p_date, p_model, 1, p_input, p_output, p_cost, now())
    ON CONFLICT (usage_date, model) DO UPDATE
        SET calls         = anthropic_usage_daily.calls + 1,
            input_tokens  = anthropic_usage_daily.input_tokens  + EXCLUDED.input_tokens,
            output_tokens = anthropic_usage_daily.output_tokens + EXCLUDED.output_tokens,
            est_cost_usd  = anthropic_usage_daily.est_cost_usd  + EXCLUDED.est_cost_usd,
            updated_at    = now();

    SELECT COALESCE(SUM(est_cost_usd), 0) INTO day_total
        FROM anthropic_usage_daily WHERE usage_date = p_date;
    RETURN day_total;
END;
$$;
