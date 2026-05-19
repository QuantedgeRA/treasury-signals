# treasury-signals — TSI backend scanner

Python scanner that powers Treasury Signal Intelligence (TSI). Detects BTC treasury 8-Ks across ~200 public companies (US + Japan + Korea + 12 more markets) within seconds of the SEC/DART/EDINET filing, runs them through Claude for impact-scored excerpts, and pushes alerts to subscribers via email, Telegram, and Slack — before the news reaches Twitter. Customer-facing dashboard lives in [`treasury-dashboard`](https://github.com/QuantedgeRA/treasury-dashboard) (Next.js on Vercel).

## What it does

Three times a day (6am, 12pm, 6pm UTC) the scan loop in `main.py` runs an idempotent pipeline:

1. **Tweet scanner** — pulls tweets from ~24 executive accounts via TwitterAPI.io, classifies for treasury signals, alerts via Telegram
2. **STRC volume tracker** — Strategy-specific issuance signal
3. **SEC EDGAR realtime** — full-text searches recent 8-Ks for bitcoin keywords, extracts BTC/USD amounts
4. **Correlation Engine v2** — 6-stream cross-signal scoring (per-company + market-wide)
5. **Daily email briefing** + **leaderboard** (7am / 8am)
6. **Purchase & sale detection** — snapshot deltas → `pending_purchases` → reconciler promotes to `confirmed_purchases` only when corroborated by EDGAR / news / global filings
7. **Regulatory scan** — US EDGAR (FTS + Atom), Japan EDINET, Korea DART, El Salvador, plus Google News across 15 languages and crypto news wires
8. **Per-cycle:** treasury sync from CoinGecko + BitcoinTreasuries.net, entity classification, name fixers, velocity tracker
9. **6am only:** shares outstanding sync from Yahoo Finance, ticker validation, ETF holdings, DeFi holdings

All purchase/sale detections route through `purchase_reconciler.py` which deduplicates, ranks by source quality, and gates snapshot deltas behind corroborating evidence.

## Architecture

```
External APIs                Pipeline                         Storage
─────────────                ────────                         ───────
TwitterAPI.io      ─┐
SEC EDGAR FTS      ─┤        scanners/         ─┐
Yahoo Finance      ─┤        pipelines/         ├──► Supabase Postgres
CoinGecko          ─┼─────►  sync/              │     • treasury_companies
BitcoinTreasuries  ─┤        alerts/            │     • confirmed_purchases
Google News (15ln) ─┤        scheduler/        ─┘     • pending_purchases
Anthropic API      ─┘                                 • confirmed_sales
                                                      • edgar_filings
                                                      • subscribers
                                                      • data_freshness
                                                      • schema_migrations

                             Outbound:
                             Telegram (paid + free + admin channels)
                             Resend (daily briefing email)
                             Sentry (error tracking)
```

## Required env vars

| Name | Used for |
|---|---|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Service role key (~219 chars, NOT the anon key) |
| `TWITTERAPI_IO_KEY` | TwitterAPI.io for tweet scraping |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `TELEGRAM_PAID_CHANNEL_ID` | Customer-facing paid channel |
| `TELEGRAM_FREE_CHANNEL_ID` | Customer-facing free channel |
| `RESEND_API_KEY` | Email delivery (Resend) |
| `ANTHROPIC_API_KEY` | LLM for narrative generation + classification |
| `SENTRY_DSN` | Error tracking — Python project DSN |

### Optional

| Name | Used for |
|---|---|
| `TELEGRAM_ADMIN_CHANNEL_ID` | Ops alerts when sources fail repeatedly. If unset, the freshness escalator silently no-ops. |
| `DART_API_KEY` | Korean filings (https://opendart.fss.or.kr — free) |
| `EDINET_API_KEY` | Japanese filings (https://disclosure2.edinet-fsa.go.jp/weee0010.aspx — free, FSA enforced from 2024) |
| `COINGECKO_API_KEY` | Higher CoinGecko rate limit |
| `CRYPTOQUANT_API_KEY` | Exchange flow data (otherwise limited fallback) |
| `DATABASE_URL` | Direct Postgres connection string. Enables AUTO mode in `migration_runner.py` (otherwise manual). |
| `SENTRY_ENVIRONMENT` | Defaults to `production` |

## Running locally

```bash
cp .env.example .env       # then fill in the env vars above
pip install -r requirements.txt
python main.py             # starts the scan loop
```

The loop runs immediately on startup, then sleeps until the next 6/12/18 UTC hour.

## Deployment

Render auto-deploys `master` on push (no `render.yaml` — service settings are in the Render dashboard). Watch logs after a push to confirm `Sentry: initialized` lines up.

Two services run from this repo:
1. **Main worker** (`python main.py`) — the 3x/day full scan loop (10 phases + post-scan synthesis, briefings, leaderboard, etc.).
2. **Fast filings cron** (`python fast_edgar.py`, schedule `* * * * *` or `*/2 * * * *`) — runs US SEC EDGAR + non-USA regulatory adapters (Japan EDINET, South Korea DART, etc.) + Claude excerpt extraction + alert dispatch every 1–2 minutes so customer-visible alert latency on new filings stays sub-60-seconds. Same env vars as the main worker (including `DART_API_KEY` and `EDINET_API_KEY` for international coverage). Without this cron, file-to-alert latency reverts to ~4 hour median / ~6 hour worst-case (the gap between scheduled scan slots).
3. **Fast tweets cron** (`python fast_tweets.py`, schedule `*/2 * * * *`) — polls the 15 priority=high X accounts (Saylor, Mallers, MARA, Metaplanet, etc.), runs the classifier + `exec_signal_detector` (Saylor-tracker pattern + analogous CEO patterns), dispatches alerts. Closes the latency gap on CEO pre-announcement signals — without it, a Saylor tracker tweet waits up to ~6h for the next 3x/day cycle. The 6s inter-account sleep (TwitterAPI.io rate-limit compliance) puts the full run at ~90s, so every-2-min is the minimum safe cadence. Env: needs `TWITTER_API_KEY` plus the same Supabase / Anthropic / Telegram / Resend vars as the main worker.

The dashboard repo (`treasury-dashboard`) auto-deploys to Vercel on push to `main`. If pushes stop appearing in Vercel, check **Project → Settings → Git → Connected Git Repository** first — the GitHub App connection has broken once before.

## Adding a database migration

Schema changes are tracked in `migrations/`. See [`migrations/README.md`](migrations/README.md) for the full workflow. TL;DR:

```bash
# 1. Write migrations/NNNN_description.sql (idempotent, IF NOT EXISTS / IF EXISTS)
# 2. Show pending state
python migration_runner.py status
# 3. Apply (auto if DATABASE_URL set, otherwise prints SQL for manual paste)
python migration_runner.py apply
```

Never edit a migration after it's been applied. To revert or change something, write a new migration.

## Key modules

| Module | Responsibility |
|---|---|
| `main.py` | Scan-loop orchestrator. Runs the 10-step pipeline 3x daily. |
| `purchase_reconciler.py` | Central dedup + source-rank routing for all purchases & sales. **Read this first** before touching any scanner that produces purchase data. |
| `treasury_sync.py` | CoinGecko + BitcoinTreasuries entity sync. Wipes-and-rewrites `treasury_companies`; preserves `shares_outstanding` across the wipe. |
| `global_filing_scanner.py` | International regulatory adapters + Google News (15 langs) + crypto wires. 5 active country adapters; 12 retired (HTML scrapers killed by SPAs/anti-bot). |
| `edgar_realtime.py` | Real-time SEC EDGAR 8-K monitor. Routes purchase-type filings through the reconciler. |
| `correlation_engine.py` | 6-stream cross-signal scoring. |
| `freshness_tracker.py` | Per-source health tracking. Escalates 3+ consecutive failures to `TELEGRAM_ADMIN_CHANNEL_ID` via `observability.notify_admin`. |
| `observability.py` | Sentry init + capture helpers + admin-channel notifier. |
| `migration_runner.py` | Applies and tracks `migrations/*.sql`. |
| `sync_protector.py` | Preserves primary-source data (BTC holdings, source attribution) across the aggregator-sync wipe. |
| `subscriber_manager.py` | User/subscriber profile management for the dashboard. |

## Hard constraints

- Git author for commits in this repo: `quantedgera <contact@quantedgeriskadvisory.com>` — pass via `git -c user.name=... -c user.email=...`, never modify the repo's git config.
- Existing features must never be replaced, only built upon. Dead code can be deleted but live functionality stays even if it could be done better.
- Frontend layout in the dashboard repo uses `lg:ml-[220px]` and `bg-[#04070d]` — don't drift.
- Stripe API routes in the dashboard use `fetch()`, not the Stripe SDK.
- `SUPABASE_KEY` here must be the service role key (~219 chars). The anon key (legacy JWT format) goes in the dashboard repo only.

## Project status

Treasury Signal Intelligence is an MVP under Quantedge Risk Advisory. Backend is on Render, dashboard is on Vercel at `app.quantedgeriskadvisory.com`. Database is Supabase Postgres with RLS. Billing is Stripe (fetch-based, no SDK).

Architectural debt items being worked through (see commit history for status): observability ✅, schema migrations ✅, dead code cleanup ✅, backend package restructure ⏳, automated tests ⏳, TypeScript migration on the frontend ⏳, replace wipe-and-rewrite with upserts ⏳.
