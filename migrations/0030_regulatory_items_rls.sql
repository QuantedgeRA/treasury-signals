-- 0030_regulatory_items_rls.sql
--
-- Deny anonymous (public anon-key) access to regulatory_items — completing the
-- deny-by-default RLS posture.
--
-- regulatory_items was the last knowingly-anon-readable non-public table. It
-- stayed open because four authenticated dashboard pages (dashboard, proposal,
-- regulatory, report) read it directly with the browser anon client. Those
-- reads were MOVED to the session-gated service-role route
-- /api/regulatory (treasury-dashboard) BEFORE this migration, so the pages keep
-- working under RLS while a leaked anon key can no longer dump the table.
--
-- ORDER OF OPERATIONS: deploy the dashboard /api/regulatory route + the 4 page
-- changes FIRST (already pushed), THEN apply this migration. The other way
-- around briefly empties those pages until the deploy lands.
--
-- Same belt-and-suspenders shape as 0027 (edgar_filings): a bare ENABLE RLS can
-- be a no-op if the table already has a permissive "allow all" SELECT policy, so
-- we also drop every existing policy. RLS on + zero policies = anon/authenticated
-- see nothing; service_role bypasses RLS, so the backend + /api/regulatory keep
-- working. Verify after applying: anon read of regulatory_items returns 0 rows;
-- service-role still returns rows.
--
-- Apply in the Supabase SQL editor (or migration_runner when DATABASE_URL set).
-- Reversible: ALTER TABLE regulatory_items DISABLE ROW LEVEL SECURITY;

ALTER TABLE regulatory_items ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE pol record;
BEGIN
  FOR pol IN
    SELECT policyname FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'regulatory_items'
  LOOP
    EXECUTE format('DROP POLICY %I ON public.regulatory_items', pol.policyname);
  END LOOP;
END $$;
