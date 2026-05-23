-- 0018_api_rate_limit_buckets.sql
--
-- Per-API-key per-minute rate-limit counters.
--
-- /docs has been advertising "100/min Pro, 500/min Team, 429 on excess"
-- since the API page shipped, but no code enforced it (recorded in
-- [[rate_limiting_aspirational]]). The strategic review at 2026-05-21
-- flagged this as a Trust issue — promising-then-not-delivering is
-- worse than not promising. This migration adds the substrate to
-- actually enforce the limits.
--
-- ARCHITECTURE
-- ============
-- One row per (api_key_hash, minute_bucket) with a count of requests
-- in that 60-second window. Increment is atomic via the
-- increment_api_rate_limit() RPC — a SECURITY DEFINER function that
-- does INSERT ... ON CONFLICT DO UPDATE in a single statement,
-- returning the new count.
--
-- WHY NOT REDIS / VERCEL KV
-- =========================
-- This deploys on Vercel where API routes run as serverless functions —
-- in-memory state doesn't persist between requests. The natural shared
-- store is the Supabase Postgres we already have. Adding a Redis/KV
-- service is an extra ops surface for a feature that needs ~1 query
-- per request.
--
-- CLEANUP
-- =======
-- Old buckets aren't auto-deleted by this migration. A separate
-- maintenance task in the scheduler can DELETE rows older than 1 hour
-- once per hour. Until that exists, the table is bounded by:
--   (active_keys × minutes_per_hour) ≈ small even at scale

CREATE TABLE IF NOT EXISTS public.api_rate_limit_buckets (
  api_key_hash    TEXT NOT NULL,
  minute_bucket   TIMESTAMPTZ NOT NULL,   -- truncated to minute, UTC
  request_count   INTEGER NOT NULL DEFAULT 1,
  created_at      TIMESTAMPTZ DEFAULT now() NOT NULL,
  PRIMARY KEY (api_key_hash, minute_bucket)
);

-- Hot path: lookup current bucket by (api_key_hash, minute_bucket) —
-- already covered by the PK. Index for cleanup queries by age:
CREATE INDEX IF NOT EXISTS idx_arl_bucket_desc
  ON public.api_rate_limit_buckets (minute_bucket DESC);


-- Atomic increment: returns the new count after upsert. Used by
-- /api/v1/auth.js after successful key validation, before returning
-- the user object. SECURITY DEFINER so the anon role can call it
-- without granting INSERT/UPDATE on the table directly.
CREATE OR REPLACE FUNCTION public.increment_api_rate_limit(
  p_api_key_hash TEXT,
  p_bucket TIMESTAMPTZ
) RETURNS INTEGER
LANGUAGE plpgsql SECURITY DEFINER
AS $$
DECLARE
  new_count INTEGER;
BEGIN
  INSERT INTO public.api_rate_limit_buckets (api_key_hash, minute_bucket, request_count)
  VALUES (p_api_key_hash, p_bucket, 1)
  ON CONFLICT (api_key_hash, minute_bucket)
  DO UPDATE SET request_count = public.api_rate_limit_buckets.request_count + 1
  RETURNING request_count INTO new_count;
  RETURN new_count;
END;
$$;

-- Allow the anon role + authenticated role to call the RPC.
-- (The function body is SECURITY DEFINER so it executes with table
-- owner privileges regardless of caller's role.)
GRANT EXECUTE ON FUNCTION public.increment_api_rate_limit(TEXT, TIMESTAMPTZ) TO anon, authenticated;
