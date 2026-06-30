# API / SDK / Security hardening

## Summary

5 commits, 39 files changed (+4567 / −1296). The headline fixes are:

1. **P0 security:** `POST /v1/upload` and `POST /v2/upload` now enforce entity authorization before any I/O, closing a cross-tenant data-pollution vulnerability.
2. **API/SDK/DB alignment:** the public OpenAPI spec, REST routes, SDK surface, and pipeline state are now mutually consistent. Six previously-undocumented v1 endpoints, both v2 sessions and v2 conflicts, and the SDK `add()` override parameters are wired up.
3. **Production hardening:** OAuth state tokens now live in Redis with a TTL (multi-worker safe), CORS rejects `*` in production at startup, and `docs/api/openapi.yaml` is auto-generated from the running app with a drift test.

All 657 tests pass (1 skipped, 0 failures). See `CHANGELOG.md` for the full entry.

## Commits (most-recent first)

| SHA | Subject |
|---|---|
| `f14648b` | docs: changelog entry |
| `c20ce14` | feat(infra): production hardening — oauth in redis, cors, openapi |
| `81b53f1` | feat(sdk): typed exceptions, async context manager, shared httpx client |
| `8ff6d70` | feat(api): align routes, schema, and engine to documented contract |
| `ada42fc` | fix(security)!: enforce entity authorization on upload routes (P0) |

## Security impact

- **P0 upload authorization** — before this PR, an authenticated key with `write` permission could upload into any entity's namespace. The fix calls `_authorize_entity` as the first statement of `upload_file`, before the file is read from disk, before MinIO is touched, before the DB lookup. The new end-to-end test (`test_upload_end_to_end_rejects_mismatched_entity`) uses the real `authorize_entity` helper (not patched) so removing the call is caught by CI.
- **CORS production wildcard** — `CORS_ALLOWED_ORIGINS=*` is now rejected at startup in production. Existing prod deployments with a wildcard must set an explicit list before upgrading.
- **OAuth state Redis** — the in-process dict broke multi-worker deployments (callback could land on a different worker). Now atomic via `GETDEL`. Redis unavailability surfaces as 503, not a silent acceptance of broken tokens.

## API contract changes

| Endpoint / field | Before | After |
|---|---|---|
| `POST /v1/memories` | `memory_type` / `confidence` / `valid_until` only via `metadata` dict | Direct body fields (precedence: explicit arg > `metadata` > chunker default) |
| `GET /v1/pipelines/{id}` | `chunk_count` (always 0), no `fact_extraction_status`, no `memory_count` | `chunk_count` removed (was misleading); new `fact_extraction_status` (success / failed / skipped) and `memory_count` |
| `POST /v1/connectors/{provider}/connect` | state in in-process dict | state in Redis (10-minute TTL, configurable) |
| `GET /v1/sessions` and friends | only in v1, not v2 | both v1 and v2 |
| `POST /v1/conflicts/{id}/resolve` | only in v1, not v2 | both v1 and v2 |

## SDK changes

- New `emerald.sdk.exceptions` module with six typed exceptions (`EmeraldAuthError`, `EmeraldNotFoundError`, `EmeraldValidationError`, `EmeraldRateLimitError`, `EmeraldServerError`, `EmeraldNetworkError`) all inheriting from `EmeraldError`. Old `httpx.HTTPStatusError` is no longer surfaced.
- `EmeraldClient` is now an async context manager: `async with EmeraldClient(...) as client:`.
- `client.upload()` reuses the shared `httpx.AsyncClient` (with a per-request timeout override) instead of building a new client per call.
- `client.add()` accepts `memory_type`, `confidence`, `valid_until` as direct kwargs.

Callers that previously caught `httpx.HTTPStatusError` must catch `EmeraldError` (or a specific subclass) instead.

## Migration

```bash
# Apply the new column
alembic upgrade head

# Required env change for production deployments with wildcard CORS
# CORS_ALLOWED_ORIGINS=https://app.example.com,https://admin.example.com
```

No data migration is required. The new columns (`pipeline_jobs.fact_extraction_status`, `pipeline_jobs.memory_count`) default to `NULL` / `0` for existing rows.

## How to review

Start at the bottom of the stack:
1. `ada42fc` — read this first; it's the smallest change but the most important.
2. `8ff6d70` — review the schema + engine + SDK changes for the override parameters and pipeline status.
3. `81b53f1` — SDK refactor (exceptions, context manager).
4. `c20ce14` — production hardening (Redis, CORS, OpenAPI generation).
5. `f14648b` — the CHANGELOG entry should match what the diffs actually do.

The tests are organized by area:
- `tests/api/test_upload_authorization.py` — P0 security
- `tests/api/test_v2_route_parity.py` — v1/v2 alignment
- `tests/api/test_oauth_state_store.py` — Redis state, 503 on failure
- `tests/api/test_cors_validation.py` — production wildcard rejection
- `tests/api/test_openapi_drift.py` — spec drift
- `tests/pipeline/test_chunk_task_no_fact_status.py` — dead-code regression
- `tests/sdk/test_add_overrides.py` — override parameters + precedence
- `tests/sdk/test_pipeline_status_fields.py` — new pipeline fields
- `tests/sdk/test_exceptions_and_context.py` — typed exceptions + context manager

## Risk

Low. All five commits are small, all have regression tests, and the security fix is a single function call that short-circuits before any I/O. The breaking changes are:
- `chunk_count` removed from `PipelineStatusResponse` (was always returning 0 anyway)
- SDK callers must catch `EmeraldError` instead of `httpx.HTTPStatusError`
- Existing prod CORS=`*` deployments must set explicit origins
