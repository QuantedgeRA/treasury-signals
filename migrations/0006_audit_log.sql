-- 0006_audit_log.sql
--
-- Append-only audit log of meaningful mutations across the product.
--
-- Background: Enterprise procurement and compliance teams ask "who changed
-- what, when?" before signing. Without an audit trail this question can't be
-- answered, full stop. This table is the source of truth.
--
-- Scope (this migration): mutations only. We capture profile updates,
-- watchlist changes, plan changes (from Stripe webhooks), saved-view
-- create/update/delete, and account deletion. We deliberately do NOT capture
-- page views or read-only API hits — those are noise, blow past Supabase's
-- free tier within weeks at any scale, and are not what compliance asks
-- about. Enterprise customers requesting full read-trail will need a
-- second migration that pipes API access logs into a separate table or
-- ships them to a SIEM.
--
-- Schema design:
--   actor_email   — email at the time of the action (denormalized so the
--                   row is interpretable even if the subscriber is later
--                   deleted)
--   actor_id      — subscriber_id at the time of the action (also
--                   denormalized for the same reason)
--   action        — short dotted slug describing the action ('profile.update',
--                   'watchlist.add', 'watchlist.remove', 'plan.upgrade',
--                   'plan.downgrade', 'saved_view.create', 'account.delete',
--                   etc.)
--   entity_type   — kind of thing being mutated ('subscriber', 'watchlist',
--                   'saved_view', 'subscription'). Optional; null for
--                   actions that don't have a clear target object.
--   entity_id     — id of the thing being mutated. Optional.
--   before        — JSONB snapshot of the relevant fields BEFORE the change
--                   (null for create actions)
--   after         — JSONB snapshot of the relevant fields AFTER the change
--                   (null for delete actions)
--   metadata      — JSONB blob for action-specific context (e.g.
--                   {"old_plan":"pro","new_plan":"team","stripe_event":"…"})
--   ip_address    — request IP (best-effort; null if unavailable)
--   user_agent    — request user-agent (best-effort; null if unavailable)
--   created_at    — when the action was performed (server time)
--
-- Append-only: rows are NEVER updated or deleted by application code. If a
-- compliance need ever requires PII redaction, do it via a separate
-- redaction process and log THAT redaction as another audit entry.

CREATE TABLE IF NOT EXISTS audit_log (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_email   TEXT NOT NULL,
  actor_id      TEXT,
  action        TEXT NOT NULL,
  entity_type   TEXT,
  entity_id     TEXT,
  before        JSONB,
  after         JSONB,
  metadata      JSONB,
  ip_address    INET,
  user_agent    TEXT,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Hot path: "show me everything user X did, most recent first"
CREATE INDEX IF NOT EXISTS idx_audit_actor_recent
  ON audit_log (actor_email, created_at DESC);

-- Hot path: "show me every {plan upgrade, account deletion} across the org"
CREATE INDEX IF NOT EXISTS idx_audit_action_recent
  ON audit_log (action, created_at DESC);

-- Hot path: time-window scans for compliance reports
CREATE INDEX IF NOT EXISTS idx_audit_created_at
  ON audit_log (created_at DESC);
