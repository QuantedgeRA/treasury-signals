-- 0025_remove_predictions.sql
--
-- Hard-delete of the predictions feature (soft-hidden 2026-05-11; product
-- strategy locked it as killed — see [[product-strategy-2026-05]] /
-- [[predictions-hard-delete-window]]). Removes the three predictions tables.
--
-- Data handling (decided 2026-06-02): ARCHIVE then drop. `predictions` (114
-- rows) and `price_predictions` (46 rows) hold real history, so they're copied
-- to _archive_* tables first and remain recoverable. `learned_weights` is the
-- accuracy-feedback store and was empty (0 rows) — dropped outright.
--
-- The code side is removed in the same PR: price_predictor.py, accuracy_tracker.py,
-- feedback_loop.py deleted; classifier DIMENSION-7 and email feedback section
-- neutralized (both already inert since soft-hide). Nothing writes/reads these
-- tables after this migration.
--
-- Apply manually in the Supabase SQL editor (DATABASE_URL unset, same as 0022-0024).
-- Idempotent-ish: the archive CREATEs use IF NOT EXISTS; re-running after the
-- DROP would archive nothing (source gone) but won't error on the drops.

-- 1) Archive the populated tables (one-time snapshot of the data).
CREATE TABLE IF NOT EXISTS _archive_predictions       AS TABLE predictions;
CREATE TABLE IF NOT EXISTS _archive_price_predictions AS TABLE price_predictions;

-- 2) Drop the live tables. learned_weights was empty — no archive.
DROP TABLE IF EXISTS price_predictions;
DROP TABLE IF EXISTS predictions;
DROP TABLE IF EXISTS learned_weights;
