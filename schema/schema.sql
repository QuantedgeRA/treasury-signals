-- schema.sql
-- Live snapshot of the Supabase public schema, captured 2026-05-11.
-- Generated via schema/_csv_to_schema.py from the metadata-dump CSV.
-- See schema/README.md for the regen workflow.
--
-- Tables + columns only. Constraints (PK / FK / UNIQUE) and indexes
-- still need to be captured separately — run schema/introspect.sql
-- Queries 2 and 3 in the Supabase SQL editor and paste the results
-- at the bottom of this file under their respective section headers.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ----------------------------------------------------------------------
-- Table: audit_log
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.audit_log (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  actor_email text NOT NULL,
  actor_id text,
  action text NOT NULL,
  entity_type text,
  entity_id text,
  before jsonb,
  after jsonb,
  metadata jsonb,
  ip_address inet,
  user_agent text,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- ----------------------------------------------------------------------
-- Table: confirmed_purchases
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.confirmed_purchases (
  id BIGSERIAL,
  purchase_id text NOT NULL,
  company text NOT NULL,
  ticker text DEFAULT ''::text,
  btc_amount numeric DEFAULT 0,
  usd_amount numeric DEFAULT 0,
  price_per_btc numeric DEFAULT 0,
  filing_date text NOT NULL,
  filing_url text DEFAULT ''::text,
  was_predicted boolean DEFAULT false,
  prediction_id text,
  prediction_lead_time_hours numeric,
  confirmed_at TIMESTAMPTZ DEFAULT now(),
  source text DEFAULT ''::text
);

-- ----------------------------------------------------------------------
-- Table: confirmed_sales
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.confirmed_sales (
  sale_id text NOT NULL,
  company text NOT NULL,
  ticker text,
  btc_amount numeric NOT NULL,
  usd_amount numeric DEFAULT 0,
  price_per_btc numeric DEFAULT 0,
  filing_date date,
  filing_url text,
  source text,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- ----------------------------------------------------------------------
-- Table: data_freshness
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.data_freshness (
  id BIGSERIAL,
  snapshot_time TIMESTAMPTZ NOT NULL,
  overall_health text DEFAULT 'unknown'::text,
  live_count integer DEFAULT 0,
  stale_count integer DEFAULT 0,
  unavailable_count integer DEFAULT 0,
  sources_json jsonb DEFAULT '[]'::jsonb,
  provenance_json jsonb DEFAULT '{}'::jsonb
);

-- ----------------------------------------------------------------------
-- Table: edgar_companies
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.edgar_companies (
  id BIGSERIAL,
  cik text NOT NULL,
  company text NOT NULL,
  ticker text NOT NULL,
  priority text DEFAULT 'medium'::text,
  is_active boolean DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- ----------------------------------------------------------------------
-- Table: edgar_filings
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.edgar_filings (
  id SERIAL,
  accession_number VARCHAR(50) NOT NULL,
  company_name VARCHAR(200),
  ticker_cik VARCHAR(50),
  filing_date date,
  form_type VARCHAR(20),
  event_type VARCHAR(20),
  btc_amount numeric DEFAULT 0,
  usd_amount numeric DEFAULT 0,
  filing_url VARCHAR(500),
  processed_at TIMESTAMPTZ DEFAULT now(),
  source text
);

-- ----------------------------------------------------------------------
-- Table: leaderboard_snapshots
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.leaderboard_snapshots (
  id BIGSERIAL,
  snapshot_date text NOT NULL,
  btc_price numeric DEFAULT 0,
  total_btc bigint DEFAULT 0,
  total_value_b numeric DEFAULT 0,
  companies_json text DEFAULT '[]'::text,
  created_at TIMESTAMPTZ DEFAULT now(),
  entity_count integer DEFAULT 0
);

-- ----------------------------------------------------------------------
-- Table: learned_weights
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.learned_weights (
  id BIGSERIAL,
  weight_key text NOT NULL,
  category text NOT NULL,
  original_weight numeric DEFAULT 0,
  learned_adjustment numeric DEFAULT 0,
  effective_weight numeric DEFAULT 0,
  success_count integer DEFAULT 0,
  failure_count integer DEFAULT 0,
  success_rate numeric DEFAULT 0,
  last_updated TIMESTAMPTZ DEFAULT now()
);

-- ----------------------------------------------------------------------
-- Table: narratives
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.narratives (
  id BIGSERIAL,
  narrative_type text NOT NULL,
  narrative_date text NOT NULL,
  content text DEFAULT ''::text,
  generated_at TIMESTAMPTZ DEFAULT now()
);

-- ----------------------------------------------------------------------
-- Table: new_entrants
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.new_entrants (
  id BIGSERIAL,
  ticker text NOT NULL,
  company text,
  btc_holdings integer DEFAULT 0,
  first_seen date DEFAULT CURRENT_DATE NOT NULL,
  notified boolean DEFAULT false
);

-- ----------------------------------------------------------------------
-- Table: notable_statements
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.notable_statements (
  id BIGSERIAL,
  statement_id text NOT NULL,
  person text NOT NULL,
  title text DEFAULT ''::text,
  date text DEFAULT ''::text,
  statement text DEFAULT ''::text,
  impact text DEFAULT ''::text,
  category text DEFAULT ''::text,
  source_url text DEFAULT ''::text,
  auto_detected boolean DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- ----------------------------------------------------------------------
-- Table: pending_purchases
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.pending_purchases (
  id BIGSERIAL,
  pending_id text NOT NULL,
  company text NOT NULL,
  ticker text NOT NULL,
  btc_amount numeric DEFAULT 0,
  usd_amount numeric DEFAULT 0,
  price_per_btc numeric DEFAULT 0,
  detected_date text NOT NULL,
  source text NOT NULL,
  source_rank integer DEFAULT 4,
  notes text DEFAULT ''::text,
  status text DEFAULT 'pending'::text,
  confirmed_at TIMESTAMPTZ,
  confirmed_by text,
  created_at TIMESTAMPTZ DEFAULT now(),
  is_new_entrant boolean DEFAULT false,
  transaction_type text DEFAULT 'purchase'::text
);

-- ----------------------------------------------------------------------
-- Table: predictions
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.predictions (
  id BIGSERIAL,
  prediction_id text NOT NULL,
  company text NOT NULL,
  ticker text DEFAULT ''::text,
  signal_type text NOT NULL,
  signal_score integer DEFAULT 0,
  signal_details text DEFAULT ''::text,
  predicted_at TIMESTAMPTZ DEFAULT now(),
  was_correct boolean,
  matched_purchase_id text,
  notes text DEFAULT ''::text
);

-- ----------------------------------------------------------------------
-- Table: price_predictions
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.price_predictions (
  id BIGSERIAL,
  prediction_date text NOT NULL,
  insights_json text DEFAULT '{}'::text,
  headline text DEFAULT ''::text,
  generated_at TIMESTAMPTZ DEFAULT now()
);

-- ----------------------------------------------------------------------
-- Table: regulatory_items
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.regulatory_items (
  id BIGSERIAL,
  item_id text NOT NULL,
  title text NOT NULL,
  category text DEFAULT ''::text,
  type text DEFAULT ''::text,
  status text DEFAULT ''::text,
  status_color text DEFAULT 'yellow'::text,
  date_updated text DEFAULT ''::text,
  summary text DEFAULT ''::text,
  impact text DEFAULT ''::text,
  btc_impact text DEFAULT ''::text,
  country text DEFAULT ''::text,
  source_url text DEFAULT ''::text,
  auto_detected boolean DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- ----------------------------------------------------------------------
-- Table: subscribers
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.subscribers (
  id BIGSERIAL,
  subscriber_id text NOT NULL,
  name text NOT NULL,
  email text NOT NULL,
  role text DEFAULT ''::text,
  company_name text NOT NULL,
  ticker text DEFAULT ''::text,
  sector text DEFAULT ''::text,
  country text DEFAULT ''::text,
  btc_holdings numeric DEFAULT 0,
  avg_purchase_price numeric DEFAULT 0,
  total_invested_usd numeric DEFAULT 0,
  plan text DEFAULT 'pro'::text,
  is_active boolean DEFAULT true,
  alert_frequency text DEFAULT 'instant'::text,
  email_briefing boolean DEFAULT true,
  telegram_chat_id text DEFAULT ''::text,
  watchlist_json jsonb DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ DEFAULT now(),
  last_active TIMESTAMPTZ DEFAULT now(),
  password_hash text DEFAULT ''::text,
  stripe_customer_id text DEFAULT ''::text,
  stripe_subscription_id text DEFAULT ''::text,
  pending_plan text DEFAULT ''::text,
  api_key text DEFAULT ''::text,
  shares_outstanding bigint DEFAULT 0,
  api_key_hash text,
  api_key_last4 text,
  api_key_created_at TIMESTAMPTZ,
  api_key_revoked_at TIMESTAMPTZ,
  user_type VARCHAR(20) DEFAULT 'entity'::character varying,
  entity_category VARCHAR(30) DEFAULT ''::character varying,
  entity_id VARCHAR(50) DEFAULT ''::character varying,
  team_id uuid,
  team_role text,
  trial_started_at TIMESTAMPTZ,
  trial_emails_sent_json jsonb DEFAULT '[]'::jsonb NOT NULL
);

-- ----------------------------------------------------------------------
-- Table: team_invites
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.team_invites (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  team_id uuid NOT NULL,
  email text NOT NULL,
  token text NOT NULL,
  invited_by text NOT NULL,
  status text DEFAULT 'pending'::text NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  accepted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- ----------------------------------------------------------------------
-- Table: teams
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.teams (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  name text NOT NULL,
  owner_id text NOT NULL,
  plan text DEFAULT 'team'::text NOT NULL,
  seat_limit integer,
  stripe_customer_id text,
  stripe_subscription_id text,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  watchlist_json jsonb DEFAULT '[]'::jsonb NOT NULL,
  slack_webhook_url text
);

-- ----------------------------------------------------------------------
-- Table: treasury_companies
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.treasury_companies (
  id BIGSERIAL,
  ticker text NOT NULL,
  company text NOT NULL,
  btc_holdings integer DEFAULT 0,
  avg_purchase_price numeric DEFAULT 0,
  total_cost_usd numeric DEFAULT 0,
  country text DEFAULT ''::text,
  sector text DEFAULT ''::text,
  is_government boolean DEFAULT false,
  data_source text DEFAULT 'seed'::text,
  last_updated TIMESTAMPTZ DEFAULT now(),
  entity_type text DEFAULT 'public_company'::text,
  shares_outstanding bigint DEFAULT 0,
  source_updated_at TIMESTAMPTZ,
  last_seen_in_source TIMESTAMPTZ
);

-- ----------------------------------------------------------------------
-- Table: treasury_history
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.treasury_history (
  id BIGSERIAL,
  ticker text NOT NULL,
  company text,
  btc_holdings integer DEFAULT 0,
  snapshot_date date DEFAULT CURRENT_DATE NOT NULL
);

-- ----------------------------------------------------------------------
-- Table: tweets
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.tweets (
  id BIGSERIAL,
  tweet_id text NOT NULL,
  author_username text NOT NULL,
  company text DEFAULT ''::text,
  tweet_text text NOT NULL,
  tweet_url text DEFAULT ''::text,
  created_at text NOT NULL,
  like_count integer DEFAULT 0,
  retweet_count integer DEFAULT 0,
  view_count integer DEFAULT 0,
  is_reply boolean DEFAULT false,
  is_signal boolean DEFAULT false,
  confidence_score integer DEFAULT 0,
  processed boolean DEFAULT false,
  inserted_at TIMESTAMPTZ DEFAULT now()
);

-- ----------------------------------------------------------------------
-- Table: user_saved_views
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.user_saved_views (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  user_id text NOT NULL,
  team_id text,
  page text NOT NULL,
  name text NOT NULL,
  filters jsonb DEFAULT '{}'::jsonb NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- ----------------------------------------------------------------------
-- Table: verification_codes
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.verification_codes (
  id BIGSERIAL,
  email text NOT NULL,
  code text NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  expires_at TIMESTAMPTZ DEFAULT (now() + '00:10:00'::interval),
  used boolean DEFAULT false
);

-- ----------------------------------------------------------------------
-- Table: whale_transactions
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.whale_transactions (
  id SERIAL,
  tx_hash VARCHAR(100) NOT NULL,
  btc_amount numeric DEFAULT 0,
  entity_name VARCHAR(200),
  direction VARCHAR(200),
  detected_at TIMESTAMPTZ DEFAULT now()
);
