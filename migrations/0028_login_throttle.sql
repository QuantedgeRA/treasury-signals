-- 0028_login_throttle.sql
--
-- Durable brute-force protection for the dashboard login route
-- (treasury-dashboard /api/auth/login). The route runs on Vercel serverless
-- (many short-lived instances), so an in-process counter is useless — a durable
-- Postgres-backed throttle is the only thing that actually works across
-- instances. Mirrors the api-rate-limit pattern from migration 0018.
--
-- Model: one row per "attempt key" (email:<addr> or ip:<addr>). Each failed
-- login increments failed_count within a rolling window; crossing the threshold
-- sets locked_until. A successful login clears the key. The login route
-- fail-OPENs if these objects are absent (pre-apply) or error — consistent with
-- the API limiter: a throttle hiccup must never lock everyone out.
--
-- Apply manually in the Supabase SQL editor (or via migration_runner when
-- DATABASE_URL is set), then it's recorded in schema_migrations.

CREATE TABLE IF NOT EXISTS login_attempts (
    attempt_key      text PRIMARY KEY,         -- 'email:foo@bar.com' | 'ip:1.2.3.4'
    failed_count     int  NOT NULL DEFAULT 0,
    first_failed_at  timestamptz NOT NULL DEFAULT now(),
    last_failed_at   timestamptz NOT NULL DEFAULT now(),
    locked_until     timestamptz
);

-- Service-role only (the login route uses the service-role key). Deny anon:
-- RLS on + no policy = no anon/authenticated access. service_role bypasses RLS.
ALTER TABLE login_attempts ENABLE ROW LEVEL SECURITY;

-- Register a failed login attempt and return the resulting state.
--   p_window_seconds  : rolling window; a first failure older than this resets.
--   p_max_attempts    : failures within the window before lock-out.
--   p_lockout_seconds : how long the lock lasts once tripped.
-- Returns (failed_count, locked_until). Row-locked (FOR UPDATE) so concurrent
-- requests from the serverless fleet increment atomically.
CREATE OR REPLACE FUNCTION register_failed_login(
    p_key text,
    p_window_seconds int,
    p_max_attempts int,
    p_lockout_seconds int
) RETURNS TABLE(failed_count int, locked_until timestamptz)
LANGUAGE plpgsql AS $$
DECLARE
    v_row login_attempts%ROWTYPE;
BEGIN
    SELECT * INTO v_row FROM login_attempts WHERE attempt_key = p_key FOR UPDATE;

    IF NOT FOUND THEN
        INSERT INTO login_attempts(attempt_key, failed_count)
        VALUES (p_key, 1)
        RETURNING login_attempts.failed_count, login_attempts.locked_until
            INTO failed_count, locked_until;
        RETURN NEXT;
        RETURN;
    END IF;

    -- If currently locked, leave the lock in place (don't extend on every hit)
    -- but report it so the caller blocks.
    IF v_row.locked_until IS NOT NULL AND v_row.locked_until > now() THEN
        failed_count := v_row.failed_count;
        locked_until := v_row.locked_until;
        RETURN NEXT;
        RETURN;
    END IF;

    -- Window elapsed since the first failure (and not locked) → start fresh.
    IF v_row.first_failed_at < now() - make_interval(secs => p_window_seconds) THEN
        UPDATE login_attempts
            SET failed_count = 1, first_failed_at = now(), last_failed_at = now(),
                locked_until = NULL
            WHERE attempt_key = p_key
            RETURNING login_attempts.failed_count, login_attempts.locked_until
                INTO failed_count, locked_until;
        RETURN NEXT;
        RETURN;
    END IF;

    -- Otherwise increment; trip the lock if we've reached the threshold.
    UPDATE login_attempts
        SET failed_count = v_row.failed_count + 1,
            last_failed_at = now(),
            locked_until = CASE
                WHEN v_row.failed_count + 1 >= p_max_attempts
                THEN now() + make_interval(secs => p_lockout_seconds)
                ELSE v_row.locked_until END
        WHERE attempt_key = p_key
        RETURNING login_attempts.failed_count, login_attempts.locked_until
            INTO failed_count, locked_until;
    RETURN NEXT;
END;
$$;

-- Return the active lock expiry for a key (NULL if not locked). Read-only
-- pre-check so a locked client is rejected before we even hash a password.
CREATE OR REPLACE FUNCTION is_login_locked(p_key text)
RETURNS timestamptz
LANGUAGE sql AS $$
    SELECT locked_until FROM login_attempts
    WHERE attempt_key = p_key AND locked_until IS NOT NULL AND locked_until > now();
$$;

-- Clear a key after a successful login.
CREATE OR REPLACE FUNCTION clear_failed_logins(p_key text)
RETURNS void
LANGUAGE sql AS $$
    DELETE FROM login_attempts WHERE attempt_key = p_key;
$$;
