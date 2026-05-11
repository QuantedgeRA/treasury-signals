-- 0010_trial_drip.sql
--
-- Trial conversion email drip — schema additions.
--
-- Background: when a user starts a Pro trial via Stripe Checkout
-- (subscription_data[trial_period_days]=7), they currently get nothing
-- until day 7. The daily Pro briefing fires for them, but there's no
-- onboarding sequence walking them through the value. Industry baseline
-- says a 5-touch trial drip lifts trial → paid conversion 25-40%.
--
-- This migration adds the two columns the cron scheduler needs:
--
--   trial_started_at        — set by the Stripe webhook when the trial
--                              checkout completes. Cron uses NOW() -
--                              trial_started_at to compute "day N" of trial.
--   trial_emails_sent_json  — JSONB array of day-codes already sent
--                              (e.g. ["welcome","day1_brief","day3_calc"]).
--                              Idempotency: cron skips a day-code already in
--                              this array, so a missed day or a replay
--                              never double-sends.
--
-- ── Why a JSON array (not separate boolean columns) ─────────────────────
-- Two reasons:
--   1. Adding/removing email types in the drip becomes a code change, not
--      a schema migration.
--   2. The set is small (≤ 5 entries) so JSONB containment ops are O(1)
--      in practice. No index needed.
--
-- ── Cleanup ─────────────────────────────────────────────────────────────
-- We deliberately do NOT clear trial_emails_sent_json when the trial
-- ends. It serves as a permanent record of what the user received, which
-- helps debug any "why didn't I get email X?" support questions.
--
-- Migration is idempotent. No backfill needed — existing subscribers have
-- NULL trial_started_at and []::jsonb sent list, which means the cron
-- skips them entirely (no retroactive welcome emails to long-time users).

ALTER TABLE subscribers
  ADD COLUMN IF NOT EXISTS trial_started_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS trial_emails_sent_json JSONB DEFAULT '[]'::jsonb NOT NULL;

-- Hot path for the cron: "find every subscriber whose trial is in days 0-7"
-- Partial index keeps it small — most subscribers aren't in trial.
CREATE INDEX IF NOT EXISTS idx_subscribers_trial_started
  ON subscribers (trial_started_at)
  WHERE trial_started_at IS NOT NULL;
