-- 0004_add_last_seen_in_source.sql
--
-- Add `last_seen_in_source` column to treasury_companies for stale-entity
-- detection.
--
-- Background: after step 8 of the architectural roadmap (replacing
-- treasury_sync's wipe-and-rewrite with field-preserving upserts), entities
-- that disappear from CoinGecko + BitcoinTreasuries.net retain their
-- last-known state in the DB instead of being deleted. The existing
-- `last_updated` column doesn't distinguish "fresh from source" from
-- "merely touched by sync" because every upsert sets it to NOW() regardless
-- of whether the entity actually appeared in source data this cycle.
--
-- This new column tracks the latter — it's only set when an entity is
-- actually upserted from source data (CoinGecko/BT). After the change to
-- _upsert_entities lands, entities not present in a source stop getting
-- their last_seen_in_source updated. _prune_stale_entities then deletes
-- rows where last_seen_in_source < 30 days ago AND btc_holdings = 0
-- (conservative — only prunes empty entities, never destroys BTC history).
--
-- Backfill: existing rows get last_seen_in_source = last_updated (proxy for
-- "this was touched recently") so they aren't immediately marked stale on
-- the next sync. New rows get NULL until the next upsert sets it.

ALTER TABLE treasury_companies ADD COLUMN IF NOT EXISTS last_seen_in_source TIMESTAMPTZ;

-- Idempotent backfill: COALESCE so re-running doesn't overwrite values
-- that the application has already set.
UPDATE treasury_companies
SET last_seen_in_source = COALESCE(last_seen_in_source, last_updated, NOW());
