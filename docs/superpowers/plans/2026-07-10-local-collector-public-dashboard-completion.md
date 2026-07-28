# Local Collector + Public Dashboard Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the financial KOL intelligence product with a local OpenCLI collector process, a protected public FastAPI/Next.js service, reliable idempotent upload, Chinese structured analysis, ntfy notifications, and deployable Docker documentation.

**Architecture:** X and Binance Square are collected by a normal background Python process on the user's local machine. The agent persists checkpoint and upload outbox state in SQLite, then sends raw posts to authenticated public collector endpoints over HTTPS. The existing FastAPI modular monolith remains the public API and analysis runtime; MySQL is the source of truth, Redis protects scheduled/analysis work, and Next.js remains the authenticated Dashboard.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, MySQL 8, SQLite, Redis, httpx, OpenCLI, OpenAI-compatible Responses API, Next.js 15, React 19, TypeScript, Docker Compose, ntfy.

## Global Constraints

- Default language is Chinese for user-facing UI and documentation.
- Keep the current directory structure and API paths unless a compatibility alias is required.
- X collection uses a local normal background process for this version; do not add launchd, local Docker, noVNC, automated X login, or automatic provider failover.
- The local X login state and Chrome profile must never be uploaded to the public service.
- Every KOL keeps an independent `interval_minutes` value with a minimum of one minute.
- A second run for the same subscription must not start while its previous run is active.
- Preserve `raw_posts.raw_text`; summaries and translations must never overwrite raw content.
- MySQL deduplication remains `UNIQUE(platform, external_id)` and is the final idempotency boundary.
- All model display output must be Chinese. Unknown stance is `unclear` / `不明确`; missing symbols is `[]`.
- Dashboard routes and data APIs require authentication. Collector endpoints use a separate machine token and never accept the admin Cookie as collector authentication.
- Do not put real passwords, model keys, collector tokens, X Cookies, or ntfy tokens in tracked files.
- Reuse an external MySQL with a dedicated database/user in production; the Compose MySQL remains available for local verification.
- Keep the dark financial terminal visual direction and repair overlap/responsive issues without redesigning unrelated pages.
- The repository is currently entirely untracked. Do not create commits or stage unrelated files until the user explicitly approves the baseline.

---

## Current Repository Baseline (2026-07-10)

### Present but not fully verified

- `backend/app/services/structurer.py` contains the requested Chinese schema, per-KOL system/user/schema parameters, symbol normalization, and a heuristic fallback.
- `backend/app/models/subscription.py` and `backend/app/models/signal.py` contain most new prompt and structured-analysis columns.
- `backend/app/db/migrations.py` and `backend/migrations/001_prompt_auth_and_signal_fields.sql` contain an initial MySQL column migration.
- `backend/app/routers/auth.py` contains username/password login, JWT, httpOnly Cookie, logout, and session endpoints.
- `backend/app/routers/admin.py` contains platform options, market arrays, per-KOL prompts, and effective prompt responses.
- `frontend/src/app/login/page.tsx`, `frontend/src/middleware.ts`, `frontend/src/lib/api.ts`, and `frontend/src/components/AdminShell.tsx` contain partial login/settings implementations.
- Focused backend tests exist for structured output, auth, admin settings, public payloads, collector factory behavior, scheduling, and notifications.

### Missing or incomplete

- No local collector application, SQLite Outbox, process scripts, or collector-specific tests exist.
- No public collector config/posts/heartbeat API or collector token verification exists.
- `RawPost` has no local-agent subscription link or durable pending-analysis state.
- Public Docker/environment files still describe old `ADMIN_PASSWORD`/`SECRET_KEY` settings and do not configure the current auth contract.
- The frontend changes have not passed a current production build or browser QA.
- The current model fallback does not extract fenced JSON or run a bounded repair pass before heuristic fallback.
- Existing ingestion calls the model inside the direct crawl path and uses a broad transaction rollback on duplicate insertion.
- The current public scheduler still assumes it can crawl platforms directly; local-agent mode is not represented.
- ntfy has code-level support, but the requested `https://ntfy.sh/yifanccc_kol_01` configuration and live test are not verified.
- README, architecture, data-source, deployment, configuration, operations, and prompt docs describe the old deployment model.

## Target Runtime

```text
Local machine
  collector-agent
    - OpenCLI X provider
    - Binance Square provider
    - per-subscription scheduler + mutex
    - SQLite checkpoints + upload outbox
             |
             | HTTPS + collector token
             v
Public Docker
  FastAPI API/analysis loop -> MySQL -> ntfy
             |
             v
  Next.js authenticated Dashboard
```

## Public Contracts

### Collector configuration

`GET /api/v1/collector/config`

```json
{
  "agentId": "home-mac-01",
  "pollSeconds": 60,
  "subscriptions": [
    {
      "id": 1,
      "platform": "x",
      "handle": "senerity",
      "intervalMinutes": 1,
      "enabled": true
    }
  ]
}
```

### Post upload

`POST /api/v1/collector/posts`

```json
{
  "agentId": "home-mac-01",
  "posts": [
    {
      "subscriptionId": 1,
      "platform": "x",
      "externalId": "181234567890",
      "authorHandle": "senerity",
      "authorName": "Senerity",
      "authorAvatarUrl": "https://pbs.twimg.com/profile_images/example.jpg",
      "publishedAt": "2026-07-10T10:20:00Z",
      "url": "https://x.com/senerity/status/181234567890",
      "rawContent": "Large SPX orders coming in...",
      "rawPayload": {"id": "181234567890"},
      "contentHash": "sha256-hex"
    }
  ]
}
```

Response status per item is exactly `accepted`, `duplicate`, or `invalid`. `accepted` means the raw post is durably stored; analysis may still be pending.

### Heartbeat

`POST /api/v1/collector/heartbeat`

```json
{
  "agentId": "home-mac-01",
  "version": "0.1.0",
  "status": "healthy",
  "providers": [
    {"platform": "x", "status": "authenticated", "message": null},
    {"platform": "binance_square", "status": "healthy", "message": null}
  ],
  "outboxPending": 0,
  "checkedAt": "2026-07-10T10:21:00Z"
}
```

---

### Task 1: Establish a Verified Baseline and Repair Partial Build Breaks

**Files:**
- Modify only if required by failures: `backend/app/**`, `backend/tests/**`, `frontend/src/**`
- Record results in: `docs/operations.md`

**Interfaces:**
- Consumes: the current untracked repository state.
- Produces: a passing backend suite and frontend production build before adding collector functionality.

- [ ] Run the backend suite in the backend container with current source and tests bind-mounted.

```bash
docker compose run --rm --no-deps \
  -v "$PWD/backend/app:/app/app:ro" \
  -v "$PWD/backend/tests:/app/tests:ro" \
  api sh -lc 'pip install --no-cache-dir pytest pytest-mock respx && pytest -q'
```

Expected: tests execute; every failure is recorded by exact test name before editing.

- [ ] Run the frontend production build.

```bash
cd frontend && npm install && npm run build
```

Expected: Next.js completes type checking and emits all routes, including `/login` and `/admin`.

- [ ] Fix only failures caused by the existing partial auth/prompt/settings changes.
- [ ] Re-run both commands and require zero failures before Task 2.

### Task 2: Complete and Validate the Structured Financial Signal Contract

**Files:**
- Modify: `backend/app/services/structurer.py`
- Modify: `backend/app/services/assets.py`
- Modify: `backend/app/services/ingestion.py`
- Test: `backend/tests/test_structurer.py`
- Test: `backend/tests/test_core_flow.py`

**Interfaces:**
- Consumes: `StructuredSignal`, `DEFAULT_SYSTEM_PROMPT`, `DEFAULT_USER_PROMPT`, and `DEFAULT_OUTPUT_SCHEMA`.
- Produces: `structure(raw_text, system_prompt, user_prompt, output_schema) -> StructuredSignal` that never aborts a batch because of malformed model text.

- [ ] Add failing cases for raw JSON, fenced JSON, leading prose followed by JSON, a repairable enum mismatch, completely invalid text, and no-symbol content.
- [ ] Add a bounded parser pipeline: direct JSON parse, fenced-object extraction, first balanced JSON object extraction, one normalization/repair attempt, then heuristic fallback.
- [ ] Validate custom output schemas before calling the model: object root, no additional properties, and all core display fields present.
- [ ] Keep the exact output fields `summary_cn`, `stance`, `stance_cn`, `symbols`, `market`, `key_points`, `confidence`, `importance`, `tags`, `action_hint`, `source_language`, `translated_text_cn`, and `risk_warning`.
- [ ] Verify the three mandatory examples plus malformed JSON.

```bash
cd backend && pytest -q tests/test_structurer.py tests/test_core_flow.py
```

Expected: English X, Chinese content, Binance Square, no symbol, and malformed output tests all pass.

### Task 3: Make Schema Migration and Raw-Post Analysis State Durable

**Files:**
- Modify: `backend/app/models/raw_post.py`
- Modify: `backend/app/models/kol.py`
- Modify: `backend/app/db/migrations.py`
- Create: `backend/migrations/002_collector_ingestion.sql`
- Test: `backend/tests/test_migrations.py`

**Interfaces:**
- Produces `RawPost.subscription_id`, `analysis_status`, `analysis_error`, `analysis_attempts`, and `analyzed_at`.
- Produces `KolProfile.avatar_url` updates from collector uploads without replacing an existing non-empty avatar with an empty value.

- [ ] Add a failing migration test that initializes the previous schema, runs migrations twice, and inspects all expected columns and unique constraints.
- [ ] Add nullable collector/analysis columns with safe defaults for existing rows; backfill old rows with signals as `completed` and unstructured rows as `pending`.
- [ ] Keep `UNIQUE(platform, external_id)` as the final duplicate barrier.
- [ ] Make the Python migration runner and documented SQL migration agree exactly.

```bash
cd backend && pytest -q tests/test_migrations.py
```

Expected: fresh schema, upgraded schema, and repeated migration all pass.

### Task 4: Finish Admin Authentication and Public API Protection

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/core/security.py`
- Modify: `backend/app/routers/auth.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_auth.py`

**Interfaces:**
- Consumes: `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH`, `JWT_SECRET`, `AUTH_COOKIE_NAME`, `COOKIE_SECURE`, and `WEB_ORIGIN`.
- Produces: `/api/auth/login`, `/api/auth/logout`, `/api/auth/session`, and reusable `require_authenticated`.

- [ ] Add tests for missing startup variables, wrong username/password, httpOnly Cookie flags, expired/invalid JWT, logout, Bearer compatibility, and protected `/api/signals`.
- [ ] Use constant-time password verification through `bcrypt`; never accept plaintext `ADMIN_PASSWORD` at runtime.
- [ ] Restrict CORS to configured origins with credentials enabled; reject wildcard origin with credentials.
- [ ] Add an in-process login attempt limiter keyed by remote address with a small bounded cache; keep it single-process and document the limitation.
- [ ] Standardize the current-user endpoint as `/api/auth/session` and keep existing route compatibility only where tests prove it is needed.

```bash
cd backend && pytest -q tests/test_auth.py tests/test_api.py tests/test_admin.py
```

Expected: unauthenticated data APIs return 401; login/session/logout flow passes.

### Task 5: Add Collector Token Authentication and Configuration/Heartbeat APIs

**Files:**
- Create: `backend/app/core/collector_security.py`
- Create: `backend/app/models/collector_agent.py`
- Create: `backend/app/routers/collector.py`
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_collector_api.py`

**Interfaces:**
- Consumes: `COLLECTOR_AGENT_ID` and `COLLECTOR_TOKEN_HASH` (SHA-256 hex of a high-entropy token).
- Produces: `require_collector`, `GET /api/v1/collector/config`, and `POST /api/v1/collector/heartbeat`.

- [ ] Add failing tests proving the admin Cookie cannot authenticate a collector request and the collector token cannot authenticate Dashboard APIs.
- [ ] Verify collector tokens by hashing the presented Bearer token and using `hmac.compare_digest` against `COLLECTOR_TOKEN_HASH`.
- [ ] Return only `id`, `platform`, `handle`, `intervalMinutes`, and `enabled` from collector config; never expose prompts, model keys, ntfy tokens, or admin data.
- [ ] Persist the latest heartbeat per `agent_id`, including provider status and outbox count.
- [ ] Reject heartbeat payloads for an `agentId` different from the configured ID.

```bash
cd backend && pytest -q tests/test_collector_api.py
```

Expected: auth-boundary, config-shape, and heartbeat persistence tests pass.

### Task 6: Add Idempotent Collector Post Upload and Pending Analysis

**Files:**
- Modify: `backend/app/routers/collector.py`
- Create: `backend/app/services/collector_ingestion.py`
- Create: `backend/app/services/analysis_queue.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_collector_ingestion.py`

**Interfaces:**
- Produces: `POST /api/v1/collector/posts` with per-item `accepted|duplicate|invalid`.
- Produces: `process_pending_posts(session, structurer, limit=10) -> int`.

- [ ] Add tests for mixed accepted/duplicate/invalid batches, subscription/platform mismatch, content size limits, missing symbols, and duplicate retries.
- [ ] Insert each post inside a nested transaction or dialect-supported upsert so one duplicate never rolls back accepted siblings.
- [ ] Set new rows to `analysis_status=pending`; return promptly after durable raw storage.
- [ ] Add a bounded background analysis loop that claims pending rows, calls the existing structurer, writes `Signal`/assets/tags, and marks completed or failed with retry count.
- [ ] Ensure repeated queue processing cannot create a second signal or a second ntfy notification.

```bash
cd backend && pytest -q tests/test_collector_ingestion.py tests/test_notifications.py
```

Expected: three repeated uploads produce one raw post, one signal, and at most one notification event.

### Checkpoint A: Public Ingestion Foundation

- [ ] Full backend tests pass.
- [ ] Fresh MySQL schema and upgraded MySQL schema both start.
- [ ] Admin and collector authentication boundaries are independent.
- [ ] A fixture upload reaches `raw_posts -> signals -> assets/tags` once.

### Task 7: Scaffold the Standalone Local Collector and SQLite Outbox

**Files:**
- Create: `collector/pyproject.toml`
- Create: `collector/collector_agent/config.py`
- Create: `collector/collector_agent/db.py`
- Create: `collector/collector_agent/models.py`
- Test: `collector/tests/test_outbox.py`

**Interfaces:**
- Consumes: `PUBLIC_API_URL`, `COLLECTOR_AGENT_ID`, `COLLECTOR_TOKEN`, `COLLECTOR_DB_PATH`, and `CONFIG_POLL_SECONDS`.
- Produces: `CollectorStore.record_fetch(subscription_id, checkpoint, posts)` and Outbox state transitions `pending -> delivered|dead_letter`.

- [ ] Define SQLite tables for subscription state, outbox posts, dead letters, and alert cooldowns.
- [ ] In one SQLite transaction, insert newly fetched posts into Outbox and advance that subscription's checkpoint.
- [ ] Keep pending rows after transport errors; delete only after `accepted` or `duplicate`; move `invalid` to dead letters with the server reason.
- [ ] Prove process restart preserves checkpoints and pending uploads.

```bash
cd collector && python -m pytest -q tests/test_outbox.py
```

Expected: restart, duplicate local insert, partial server response, and retry tests pass.

### Task 8: Implement Collector API Client and Per-KOL Scheduler

**Files:**
- Create: `collector/collector_agent/api_client.py`
- Create: `collector/collector_agent/scheduler.py`
- Create: `collector/collector_agent/main.py`
- Test: `collector/tests/test_scheduler.py`
- Test: `collector/tests/test_api_client.py`

**Interfaces:**
- Consumes: the collector config/posts/heartbeat contracts from Tasks 5-6.
- Produces: `CollectorScheduler.run_once(now)` and `python -m collector_agent`.

- [ ] Poll public configuration every 60 seconds by default and update local scheduling state without deleting pending Outbox rows.
- [ ] Maintain one in-process lock per subscription; if a run is active, skip that subscription without advancing checkpoint.
- [ ] Calculate `next_check_at` from completion time plus `interval_minutes`.
- [ ] Upload pending rows in bounded batches with exponential backoff capped at five minutes.
- [ ] Send heartbeat independently from post upload so an empty feed is still observable.

```bash
cd collector && python -m pytest -q tests/test_scheduler.py tests/test_api_client.py
```

Expected: 1/2/5-minute subscriptions run independently and a slow two-minute task never overlaps itself.

### Task 9: Implement the Local OpenCLI X Provider

**Files:**
- Create: `collector/collector_agent/providers/base.py`
- Create: `collector/collector_agent/providers/x_opencli.py`
- Test: `collector/tests/fixtures/opencli_x.yaml`
- Test: `collector/tests/test_x_provider.py`
- Modify: `docs/data-sources.md`

**Interfaces:**
- Produces: `Provider.fetch(handle, checkpoint, limit) -> list[CollectedPost]` and provider health `authenticated|login_required|failed`.

- [ ] Run `opencli twitter --help` on the target machine and lock the actual supported command in a test; do not assume the current server-side `twitter tweets` subcommand is correct.
- [ ] Parse external ID, text, URL, author handle/name/avatar, and UTC publication time from fixture output.
- [ ] Filter checkpoint duplicates numerically for X snowflake IDs and return posts oldest-first.
- [ ] Detect login/verification failures from process exit/output, return `login_required`, and leave checkpoint untouched.
- [ ] Never log OpenCLI environment, browser Cookie values, authorization headers, or raw Chrome profile paths.

```bash
cd collector && python -m pytest -q tests/test_x_provider.py
```

Expected: fixture parsing, checkpoint filtering, timeout, malformed output, and login-required tests pass.

### Task 10: Implement Binance Square Provider and Provider Health Alerts

**Files:**
- Create: `collector/collector_agent/providers/binance_square.py`
- Create: `collector/collector_agent/alerts.py`
- Test: `collector/tests/fixtures/binance_square.html`
- Test: `collector/tests/test_binance_provider.py`
- Test: `collector/tests/test_alerts.py`

**Interfaces:**
- Produces the same `CollectedPost` contract as X.
- Consumes `NTFY_SERVER`, `NTFY_TOPIC`, and optional `NTFY_TOKEN` for local session/provider alerts.

- [ ] Parse public Binance Square fixtures without a login requirement and isolate markup changes as provider failures.
- [ ] Keep Binance and X checkpoints independent.
- [ ] Send one alert when a provider enters `login_required` or repeated failure state, then enforce a configurable cooldown.
- [ ] Send one recovery message when the provider becomes healthy again.

```bash
cd collector && python -m pytest -q tests/test_binance_provider.py tests/test_alerts.py
```

Expected: provider isolation and alert cooldown/recovery tests pass.

### Task 11: Add Local Background Process Scripts

**Files:**
- Create: `scripts/collector-start.sh`
- Create: `scripts/collector-status.sh`
- Create: `scripts/collector-logs.sh`
- Create: `scripts/collector-stop.sh`
- Create: `collector/.env.example`

**Interfaces:**
- Consumes the collector environment contract from Task 7.
- Produces PID/log files under configurable local runtime paths, defaulting to `.runtime/collector.pid` and `.runtime/collector.log`.

- [ ] Start with `nohup` only after checking that no live PID already exists.
- [ ] Make status distinguish running, stale PID, and stopped states.
- [ ] Make stop send `TERM`, wait for graceful SQLite flush, then remove only its own stale PID file.
- [ ] Add `.runtime/` and collector SQLite files to `.gitignore` without ignoring fixtures.

Verification:

```bash
./scripts/collector-start.sh
./scripts/collector-status.sh
./scripts/collector-logs.sh --lines 20
./scripts/collector-stop.sh
```

Expected: one process starts, a second start is rejected, status is accurate, and stop leaves no running collector.

### Checkpoint B: Local-to-Public Flow

- [ ] Local X fixture and Binance fixture enter SQLite Outbox.
- [ ] Simulated network outage leaves Outbox intact.
- [ ] Network recovery uploads each post once and clears delivered rows.
- [ ] Provider login failure does not advance checkpoint and produces one cooled-down ntfy alert.

### Task 12: Finish Settings UI and Authenticated Frontend Session Behavior

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/components/AdminShell.tsx`
- Modify: `frontend/src/app/login/page.tsx`
- Modify: `frontend/src/middleware.ts`

**Interfaces:**
- Consumes `/api/auth/*`, `/api/admin/config-options`, and `/api/admin/subscriptions`.
- Produces a login redirect, logout flow, platform select, default-all market multiselect, and editable effective system/user/schema fields.

- [ ] Make all frontend fetches use `credentials: include`; on an expired API session, redirect to `/login` while preserving the intended route.
- [ ] Align the middleware Cookie name with `AUTH_COOKIE_NAME` through the web runtime environment; do not leave a hard-coded mismatch.
- [ ] Preserve X and Binance platform values exactly as backend enums.
- [ ] Show the effective prompt/schema for existing KOLs and save explicit per-KOL values through PATCH.
- [ ] Validate schema JSON client-side and keep server validation authoritative.

```bash
cd frontend && npm run build
```

Expected: production build passes with no TypeScript errors.

### Task 13: Complete Feed, KOL, Asset, and Collector Health Presentation

**Files:**
- Modify: `frontend/src/components/FeedCard.tsx`
- Modify: `frontend/src/app/kols/page.tsx`
- Modify: `frontend/src/app/kols/[id]/page.tsx`
- Modify: `frontend/src/app/assets/page.tsx`
- Modify: `frontend/src/app/globals.css`

**Interfaces:**
- Consumes the existing authenticated signal/KOL/asset API plus collector heartbeat status.
- Produces complete Chinese signal cards and non-overlapping desktop/mobile entity pages.

- [ ] Display summary, Chinese stance, symbols, key points, tags, importance, confidence, action hint, risk warning, raw text, translation, and prompt version.
- [ ] Keep symbol badges clickable and connected to existing symbol filtering/routes.
- [ ] Display real avatar URLs when available and platform marks for X/Binance; use the current deterministic fallback only when no avatar exists.
- [ ] Add collector last-seen/provider status to KOL/settings views without decorative left color strips.
- [ ] Repair text wrapping, grid min-width, sticky panel, and mobile overflow issues at the required viewports.

Verification:

```bash
cd frontend && npm run build
```

Expected: build passes; browser QA in Task 16 finds no overlap or horizontal overflow.

### Task 14: Finalize ntfy Content and Exactly-Once Notification Behavior

**Files:**
- Modify: `backend/app/services/notifications.py`
- Modify: `backend/app/models/notification.py`
- Modify: `backend/app/db/migrations.py`
- Test: `backend/tests/test_notifications.py`

**Interfaces:**
- Consumes completed `Signal` rows.
- Produces one notification event per `(signal_id, notification_rule_id)`.

- [ ] Add a unique notification-event constraint and handle repeated dispatch as a no-op.
- [ ] Format notifications with KOL, Chinese stance, symbols, summary, top key points, and source URL.
- [ ] Preserve `require_asset` behavior so no-symbol signals do not crash or notify when the rule requires an asset.
- [ ] Configure local/private defaults as `NTFY_SERVER=https://ntfy.sh` and `NTFY_TOPIC=yifanccc_kol_01` only in `.env`, not source.
- [ ] Send one explicit test notification after deployment configuration is loaded and record the HTTP result without exposing tokens.

```bash
cd backend && pytest -q tests/test_notifications.py
```

Expected: retry and duplicate dispatch tests still produce one event and one publish call.

### Task 15: Align Docker, Environment, MySQL Reuse, and Documentation

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/configuration.md`
- Modify: `docs/data-sources.md`
- Modify: `docs/deployment.md`
- Modify: `docs/operations.md`
- Modify: `docs/prompt-guide.md`

**Interfaces:**
- Produces one documented public Compose deployment and one documented local collector process.

- [ ] Remove old plaintext `ADMIN_PASSWORD` and `SECRET_KEY` examples; document safe generation for bcrypt password hash, JWT secret, and collector token hash.
- [ ] Add `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH`, `JWT_SECRET`, `AUTH_COOKIE_NAME`, `COOKIE_SECURE`, `WEB_ORIGIN`, `COLLECTOR_AGENT_ID`, `COLLECTOR_TOKEN_HASH`, ntfy, model, and analysis-loop settings.
- [ ] Make the public API default to local-agent collection mode; retain X official API as an optional future/provider path, not the active requirement.
- [ ] Document external MySQL setup with a dedicated database and minimum-privilege user; keep Compose MySQL for local verification.
- [ ] Document first X login, OpenCLI health check, start/status/logs/stop, Outbox recovery, dead-letter inspection, migration, backup, and rollback.

Verification:

```bash
docker compose config --quiet
```

Expected: configuration validates without printing or committing secret values.

### Task 16: End-to-End Verification and Browser QA

**Files:**
- Create: `backend/tests/test_collector_e2e.py`
- Create: `docs/verification.md`
- Modify only for discovered defects: relevant implementation files.

**Interfaces:**
- Verifies the complete local fixture -> public upload -> analysis -> Dashboard -> ntfy path.

- [ ] Run full backend and collector suites.

```bash
cd backend && pytest -q
cd ../collector && python -m pytest -q
```

- [ ] Build public images and start the complete stack.

```bash
docker compose up --build -d
docker compose ps
curl -fsS http://localhost:8010/health
```

- [ ] Verify unauthenticated `/` redirects to `/login`, authenticated Dashboard loads, logout blocks the API, BTC/SPX search works, and a symbol badge filters/navigates.
- [ ] Use Playwright/browser inspection at `1440x900`, `1280x800`, and `390x844`; capture screenshots and assert no horizontal overflow, overlapping text, blank charts, or inaccessible controls.
- [ ] Upload English X, Chinese, Binance, no-symbol, and malformed-model fixtures and verify each produces a durable raw post and a safe Chinese result.
- [ ] Verify a repeated local upload creates no duplicate raw post, signal, asset relation, tag relation, or ntfy event.
- [ ] Record exact commands, counts, URLs, screenshots, and any remaining external prerequisite in `docs/verification.md`.

### Final Acceptance Checklist

- [ ] Local normal background collector runs with start/status/logs/stop scripts.
- [ ] X login state remains local and login loss does not advance checkpoint.
- [ ] Each KOL has an independent minute interval and no overlapping run.
- [ ] SQLite Outbox survives restart/network failure and retries safely.
- [ ] Public upload is authenticated and idempotent.
- [ ] Raw content is preserved; structured analysis is Chinese and complete.
- [ ] Malformed model output and missing symbols do not stop processing.
- [ ] Dashboard and all data APIs require login; logout invalidates access.
- [ ] Settings support X/Binance, default-all market selection, and effective per-KOL prompts/schema.
- [ ] Feed/KOL/asset pages show avatars, platform marks, complete signal fields, and no layout overlap.
- [ ] ntfy content and provider-health alerts work without duplicate sends.
- [ ] Docker, external MySQL reuse, migration, local collector, operations, and recovery docs are current.
- [ ] Backend tests, collector tests, frontend build, Docker startup, and browser QA all pass.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| OpenCLI command or output changes | X collection stops | Lock actual command with fixture/parser tests; heartbeat and ntfy report provider failure; do not advance checkpoint. |
| Local machine sleeps or exits | Minute-level monitoring pauses | Show stale heartbeat in Dashboard; Outbox/checkpoint resume after restart; document that this MVP requires an awake machine. |
| API accepts raw post but analysis process stops | Content is visible but unstructured | Durable `analysis_status=pending` and periodic DB-backed reconciliation loop. |
| Duplicate upload after timeout | Duplicate summary/notification | MySQL raw-post unique key, one signal per raw post, one notification per signal/rule. |
| Custom schema is incompatible with Dashboard | Analysis repeatedly fails | Validate required core fields on save and before model invocation; keep default schema as fallback. |
| Cross-origin Cookie configuration is wrong | Login loops or API 401 | Prefer one public origin with reverse-proxied `/api`; test Cookie/CORS behavior in Docker and browser. |
| Public ntfy topic can be guessed | Data disclosure | Use the provided topic for current private testing, then rotate to a high-entropy topic or authenticated ntfy before broad public exposure. |

## Intentional Non-Goals for This Plan

- launchd/systemd service installation.
- Local collector Docker image.
- Automated X username/password/2FA login.
- Multi-agent coordination or remote agent management UI.
- Automatic switching among OpenCLI, X official API, and third-party providers.
- Historical market-price backtesting or trade execution.
