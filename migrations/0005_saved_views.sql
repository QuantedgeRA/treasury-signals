-- 0005_saved_views.sql
--
-- Per-user (and optionally team-shared) saved views for filterable pages.
--
-- Background: power users on the Team plan re-apply the same filter set
-- every visit (e.g. "miners with BTC > 1k", "EU public companies sorted by
-- adoption velocity"). Without persistence the product is a viewer, not a
-- workspace. Saved views are the bridge.
--
-- Schema design:
--   user_id    — owner of the view (always set, even for team-shared views)
--   team_id    — when null, the view is private to user_id
--                when set, the view is visible to every member of team_id
--                The 'Share with team' toggle in the UI flips this.
--                Forward-compatible with the upcoming teams table; today no
--                team rows exist yet, so all views are effectively per-user.
--   page       — short string identifying the surface ('leaderboard',
--                'research', 'purchases', 'regulatory', 'competitive', etc.)
--                Indexed alongside user_id and team_id for fast lookups.
--   name       — user-facing label ('My EU shortlist', 'Big Q4 buyers')
--   filters    — JSONB blob of the filter state. Schema is page-specific;
--                we do not enforce a structure here so each page can evolve
--                its filter shape independently.
--
-- Row-level access control:
--   Read: a row is visible to user_id, OR to anyone whose subscriber row
--         has team_id matching the view's team_id (RLS to be wired when
--         teams ship; for now Supabase service-role key is used).
--   Write: only user_id may UPDATE/DELETE their views.
--
-- Cascade behavior: dropping a subscriber will leave dangling saved_views
-- rows, but they're harmless — readers filter by the current user_id.

CREATE TABLE IF NOT EXISTS user_saved_views (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     TEXT NOT NULL,
  team_id     TEXT,
  page        TEXT NOT NULL,
  name        TEXT NOT NULL,
  filters     JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at  TIMESTAMPTZ DEFAULT NOW(),
  updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Hot path: "show me this user's saved views for /leaderboard"
CREATE INDEX IF NOT EXISTS idx_saved_views_user_page
  ON user_saved_views (user_id, page);

-- Hot path: "show me every saved view shared with this team for /leaderboard"
-- Partial index keeps it small — team_id is null on the majority of rows.
CREATE INDEX IF NOT EXISTS idx_saved_views_team_page
  ON user_saved_views (team_id, page)
  WHERE team_id IS NOT NULL;
