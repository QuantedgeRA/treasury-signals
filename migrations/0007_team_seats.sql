-- 0007_team_seats.sql
--
-- Team seats infrastructure for the Team and Enterprise tiers.
--
-- Background: the pricing page advertises "up to 5 seats" on Team and
-- "unlimited seats" on Enterprise, but until now the product had no
-- concept of a team. This migration adds three things:
--
--   1. teams           — one row per organization on a Team/Enterprise sub
--   2. team_invites    — pending email invites (token-based)
--   3. subscribers.team_id + subscribers.team_role — membership + role
--
-- ── Membership model ─────────────────────────────────────────────────────
--   - One team per user (MVP). A subscriber row has at most one team_id.
--     Multi-team membership is a future migration if/when needed.
--   - Two roles: 'owner' | 'member'. Admin tier deferred — for now the
--     owner does invites/removals; members read.
--   - When a team owner leaves (rare; deferred), the team must be transferred
--     or deleted. Today the API blocks this; we'll add transfer in a follow-up.
--
-- ── Plan inheritance ─────────────────────────────────────────────────────
--   - Members inherit the team's plan (subscribers.plan tracks team.plan).
--   - Stripe webhook propagates plan changes from the owner's subscription
--     down to every team member.
--   - When a member leaves the team, their subscriber.plan reverts to 'free'.
--
-- ── Seat enforcement ─────────────────────────────────────────────────────
--   - Hard cap at teams.seat_limit (5 for Team, NULL = unlimited for
--     Enterprise). Enforced by the invite API, not in the DB — we want a
--     clean 'Seat limit reached' error, not a constraint violation.
--   - Pending invites count against the seat cap (so 4 active members + 1
--     pending = full).
--
-- ── Invite tokens ────────────────────────────────────────────────────────
--   - 32-byte URL-safe random token, generated server-side.
--   - 7-day expiry by default (configurable per-invite).
--   - Status transitions: pending → (accepted | cancelled | expired).
--   - Invites are NEVER deleted, just marked — preserves audit trail.

-- Teams table
CREATE TABLE IF NOT EXISTS teams (
  id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name                    TEXT NOT NULL,
  owner_id                TEXT NOT NULL,    -- subscriber_id of the owner
  plan                    TEXT NOT NULL DEFAULT 'team',  -- 'team' | 'enterprise'
  seat_limit              INTEGER,           -- NULL = unlimited (Enterprise)
  stripe_customer_id      TEXT,
  stripe_subscription_id  TEXT,
  created_at              TIMESTAMPTZ DEFAULT NOW(),
  updated_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_teams_owner ON teams (owner_id);
CREATE INDEX IF NOT EXISTS idx_teams_stripe_customer ON teams (stripe_customer_id) WHERE stripe_customer_id IS NOT NULL;

-- Team invites — token-based pending memberships
CREATE TABLE IF NOT EXISTS team_invites (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  team_id       UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  email         TEXT NOT NULL,
  token         TEXT NOT NULL UNIQUE,
  invited_by    TEXT NOT NULL,    -- subscriber_id of the inviter
  status        TEXT NOT NULL DEFAULT 'pending',
  expires_at    TIMESTAMPTZ NOT NULL,
  accepted_at   TIMESTAMPTZ,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Hot path: token lookup on accept (filtered to pending so the partial
-- index stays compact even after thousands of accepted/cancelled rows).
CREATE INDEX IF NOT EXISTS idx_team_invites_token_pending
  ON team_invites (token) WHERE status = 'pending';

-- Hot path: "what teams has this email been invited to?" + dedup checks
CREATE INDEX IF NOT EXISTS idx_team_invites_email_status
  ON team_invites (email, status);

-- Hot path: list pending invites for a team (settings page)
CREATE INDEX IF NOT EXISTS idx_team_invites_team_status
  ON team_invites (team_id, status);

-- Subscribers gain team membership fields
ALTER TABLE subscribers
  ADD COLUMN IF NOT EXISTS team_id   UUID,
  ADD COLUMN IF NOT EXISTS team_role TEXT;  -- 'owner' | 'member'

CREATE INDEX IF NOT EXISTS idx_subscribers_team
  ON subscribers (team_id) WHERE team_id IS NOT NULL;

-- A subscriber should not have a team_role without a team_id, and vice versa.
-- We don't enforce this with a CHECK constraint at the DB level (it would
-- block partial state during the brief moment between assigning team_id
-- and team_role in a transaction), but the API guarantees it.
