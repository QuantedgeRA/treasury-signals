-- 0027_edgar_filings_rls.sql
--
-- Deny anonymous (public anon-key) access to edgar_filings.
--
-- The resilience review found edgar_filings is anon-readable. Unlike
-- leaderboard_snapshots (public landing page / embed / public-data page) and
-- regulatory_items (read by 4 authenticated pages via the browser anon client),
-- edgar_filings's only dashboard reader was the /status health page, which
-- probed it via the anon client. That read was MOVED to the service-role route
-- /api/status/freshness (commit on the dashboard) BEFORE this migration, so the
-- status page keeps working under RLS. The backend uses the service_role key
-- (confirmed) and bypasses RLS. So enabling RLS with no anon policy is safe
-- defense-in-depth: backend + status page keep working, and a direct anon REST
-- hit to /rest/v1/edgar_filings now returns 0 rows.
--
-- ORDER OF OPERATIONS: deploy the dashboard /api/status/freshness change first
-- (already pushed), THEN apply this migration. Doing it the other way around
-- briefly shows edgar_filings as "never" on /status until the deploy lands.
--
-- NOT enabling RLS on leaderboard_snapshots (intentionally public — landing/
-- embed/public-data read it via anon) or regulatory_items (4 authenticated
-- pages read it via the anon client; deny-anon would break them without first
-- moving those reads to authenticated server routes — a separate refactor; the
-- data is public regulatory-filing info, low severity).
--
-- The genuinely-sensitive tables (subscribers, filing_excerpts, mnav_history,
-- pre_announcement_signals, entity_wallets, teams) were verified already
-- RLS-protected (anon -> 0 rows) — no change needed.
--
-- Apply manually in the Supabase SQL editor (DATABASE_URL unset, same as 0022-0026).
-- Reversible: ALTER TABLE edgar_filings DISABLE ROW LEVEL SECURITY;
--
-- NOTE (2026-06-07): the first attempt at this migration was just
-- `ENABLE ROW LEVEL SECURITY`, but a live anon probe afterwards still returned
-- rows. The table already had RLS on *with a permissive "allow all" SELECT
-- policy* (created with the table). Enabling RLS was therefore a no-op. The
-- correct fix is to ALSO drop every pre-existing policy: with RLS on and zero
-- policies, anon/authenticated see no rows; service_role bypasses RLS, so the
-- backend and /api/status/freshness keep working.

ALTER TABLE edgar_filings ENABLE ROW LEVEL SECURITY;

-- Drop ALL existing policies on edgar_filings. Any permissive read policy here
-- is what was leaking rows to the anon key. After this, no policy grants
-- anon/authenticated access -> deny-all to non-service-role roles.
DO $$
DECLARE pol record;
BEGIN
  FOR pol IN
    SELECT policyname FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'edgar_filings'
  LOOP
    EXECUTE format('DROP POLICY %I ON public.edgar_filings', pol.policyname);
  END LOOP;
END $$;
