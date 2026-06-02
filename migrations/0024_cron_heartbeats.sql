-- 0024_cron_heartbeats.sql
--
-- Make short-interval Render crons observable.
--
-- fast_edgar.py (the */2 cron behind the "sub-60s" 8-K alert promise) emitted
-- no signal of its own, so whether it was actually deployed/running was
-- unobservable from data — the same blind spot that left the fast-tweets cron
-- silently dead for weeks (see [[render-topology]]). The freshness snapshot
-- table can't absorb a per-cron beat (it's a write-all-sources-once-per-cycle
-- model owned by main.py's post_scan), so crons write a lightweight row here
-- instead. main.py's freshness phase reads this and folds each cron's liveness
-- into the normal freshness snapshot + escalation path.
--
-- One row per cron (cron_name is the PK), upserted each run.
--
-- Apply manually in the Supabase SQL editor (DATABASE_URL unset, same as 0022/0023).

CREATE TABLE IF NOT EXISTS cron_heartbeats (
    cron_name    text PRIMARY KEY,
    last_run_at  timestamptz NOT NULL,
    last_status  text,                 -- 'ok' | 'error'
    detail       text
);
