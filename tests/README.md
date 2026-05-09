# tests/

Pytest test suite. Run from the repo root:

```bash
pytest                            # all tests
pytest tests/pipelines            # one subpackage
pytest tests/pipelines/test_purchase_reconciler.py -v
pytest -k "test_snapshot"         # by name pattern
pytest -m "not slow"              # skip slow tests (currently none marked)
```

## Layout

Tests mirror the package layout: `tests/<subpackage>/test_<module>.py` corresponds to `treasury_signals/<subpackage>/<module>.py`.

```
tests/
├── conftest.py                       # shared fixtures (mock_supabase, supabase_with)
└── pipelines/
    ├── test_purchase_reconciler.py   # 46 tests — data-integrity heart of the pipeline
    └── test_classifier.py            # 27 tests — tweet → signal score
```

## Conventions

- **Pure functions first** — helpers with no side effects (normalization, math, predicates) get exhaustive coverage. Cheap and catches refactors.
- **Behavior over implementation** — integration tests verify *which table got upserted with what payload*, not the internal call sequence. Lets the implementation evolve.
- **Mock at the boundary** — `mock_supabase` fixture replaces the supabase client wholesale. No real DB connections in tests; the suite runs in <3s.
- **Lock in actual behavior** — when test reveals a real-but-known gap (e.g., Japan `.T` ticker not stripped by reconciler dedup), the test asserts the *current* behavior with a comment, rather than encoding aspirational fixes.

## Coverage targets

Current focus is the two paths where bugs = wrong data sold to paying customers:

| Module | Why critical | Coverage |
|---|---|---|
| `pipelines/purchase_reconciler.py` | Dedup + source-rank routing for all purchases & sales | High |
| `pipelines/classifier.py` | Tweet → signal score (drives Telegram alerts) | High |

## Future tests (not yet written)

- `pipelines/correlation_engine.py` — 6-stream cross-signal scoring
- `pipelines/filing_parser.py` — LLM extraction of structured BTC data
- `sync/treasury_sync.py` — wipe-and-rewrite + shares_outstanding preservation
- `sync/sync_protector.py` — primary-source restoration after aggregator overwrite
- `scanners/global_filing_scanner.py` — adapters with mocked HTTP responses
- `scanners/edgar_realtime.py` — FTS hit parsing (the field-name bug that hid edgar_filings for 28+ days would have been caught here)
- Frontend `auth-server.js` `verifyPassword` — both the new scrypt path and the legacy SHA-256 fallback (needs JS test harness setup; see step 6 follow-up)

## Adding a new test

1. Create `tests/<subpackage>/test_<module>.py` (and `__init__.py` if the subdir is new).
2. Use existing fixtures from `conftest.py` where possible.
3. If you need to mock something new, add a fixture to `conftest.py` so other tests can reuse it.
4. Run the suite: `pytest`.
5. The test goes in the same PR as the code change it covers.
