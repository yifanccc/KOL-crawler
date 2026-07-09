# KOL Signal Crawler Design

Date: 2026-07-09

## 1. Project Goal

Build a small-scale financial KOL monitoring system for personal use. The system periodically checks subscribed KOLs, stores new posts without duplication, uses an OpenAI-compatible model to extract structured trading signals, pushes high-value updates through ntfy, and exposes a polished public read-only web interface.

The product is anchored on financial trading KOLs, not general social media monitoring.

Primary markets for v1:

- US stocks
- Crypto
- A-shares, for symbol recognition and filtering only

Primary data sources for v1:

- X / Twitter through official API as the stable source
- Binance Square through an isolated experimental Playwright collector, preferably without login state

## 2. Confirmed Product Decisions

- Scale: 10-30 KOL subscriptions.
- Scheduling: per-KOL `interval_minutes`, minimum 1 minute.
- Access model: public read-only pages plus private logged-in management pages.
- Model integration: OpenAI-compatible provider configuration through `base_url`, `api_key`, `model`, and generation parameters.
- Database: MySQL. Docker Compose includes MySQL by default, but deployment can reuse an existing MySQL instance through `DATABASE_URL`.
- Runtime architecture: FastAPI modular monolith, MySQL, Redis, Next.js, and an optional Playwright worker for Binance Square.
- Homepage: trading signal feed, styled as a modern signal tape.
- Visual direction: Graphite / Cyan palette, not retro green terminal.
- Notification: ntfy pushes only actionable trading signals by default, with configurable rules.

## 3. Out Of Scope For V1

- Multi-tenant accounts, billing, or team permissions.
- Trade execution, brokerage connection, portfolio management, or backtesting.
- A-share community collection from Xueqiu, WeChat public accounts, Eastmoney, Tonghuashun, or similar platforms.
- Distributed queue infrastructure such as Celery for the first version.
- Treating Binance Square Playwright scraping as a guaranteed stable data source.
- Turning model summaries into buy/sell instructions. The UI and notification copy should present research signals, not investment advice.

## 4. Architecture

Use a modular monolith to keep deployment and operations simple while preserving clean boundaries.

```text
Next.js Web
  - Public read-only signal feed
  - KOL detail pages
  - Asset/tag filtering
  - Private management pages

FastAPI API + Scheduler
  - Subscription manager
  - Collector adapters
  - LLM structuring
  - Signal storage
  - ntfy notification engine
  - Admin/auth endpoints

MySQL
  - Business records
  - Raw posts
  - Structured signals
  - Checkpoints
  - Notification history

Redis
  - Per-KOL crawl locks
  - Lightweight scheduler runtime state

Playwright worker, optional
  - Binance Square public-page collector
```

### 4.1 Module Boundaries

`subscription_manager`

- Stores KOL subscription configuration.
- Owns `interval_minutes`, `next_check_at`, `checkpoint`, enable/disable state, and selected model/prompt.

`collectors`

- Defines a common `CollectorAdapter` interface.
- Implements `XOfficialCollector`.
- Implements `BinanceSquarePlaywrightCollector` as experimental.

`structurer`

- Calls the configured OpenAI-compatible model.
- Enforces JSON schema validation.
- Retries malformed structured outputs once.

`signals`

- Stores raw posts and structured signals.
- Provides filtering APIs for public pages.

`notifications`

- Evaluates ntfy rules.
- Sends notifications.
- Records success/failure and supports manual retry.

`admin`

- Handles login.
- Provides CRUD for subscriptions, model configs, prompts, ntfy rules, and retry actions.

## 5. Scheduling, Checkpoint, And Deduplication

Scheduler behavior:

```text
Every minute:
  1. Find enabled subscriptions where next_check_at <= now.
  2. Try Redis lock crawl:{platform}:{kol_id}.
  3. Skip if the lock already exists.
  4. Fetch new posts from the collector.
  5. Insert raw posts with database-level unique constraints.
  6. Structure only newly inserted posts.
  7. Apply notification rules.
  8. Advance checkpoint only after successful processing.
  9. Update last_checked_at, last_success_at, and next_check_at.
```

Anti-overlap rules:

- Same KOL subscription must not run concurrently.
- Redis lock TTL should be longer than expected crawl duration, initially 3-5 minutes.
- If one crawl takes longer than the configured interval, the next tick skips that subscription.

Deduplication rules:

- `raw_posts(platform, external_id)` is unique.
- `signals(raw_post_id)` is unique.
- For Binance Square, prefer a stable post id or canonical URL. If unavailable, use `author + published_at + normalized_text_hash`.

Checkpoint rules:

- X checkpoint stores `since_id` or the latest successfully processed post id/time.
- Binance Square checkpoint stores canonical post id/URL or the fallback hash cursor.
- LLM or ntfy failure must not lose the raw post.
- ntfy failure does not block storage; it records a failed notification event for retry.

## 6. Data Model

Core tables:

```text
users
  id
  email
  password_hash
  created_at
  updated_at

model_configs
  id
  name
  base_url
  api_key_encrypted
  model
  temperature
  is_default
  created_at
  updated_at

kol_profiles
  id
  display_name
  avatar_url
  description
  primary_market
  created_at
  updated_at

subscriptions
  id
  kol_profile_id
  platform
  platform_account_id
  platform_handle
  interval_minutes
  prompt
  model_config_id
  checkpoint
  next_check_at
  last_checked_at
  last_success_at
  enabled
  created_at
  updated_at

raw_posts
  id
  platform
  external_id
  url
  author_handle
  author_name
  published_at
  raw_text
  raw_json
  content_hash
  created_at

signals
  id
  raw_post_id
  subscription_id
  actionable
  stance
  summary
  evidence_json
  horizon
  confidence
  risk_notes
  structured_json
  structured_status
  created_at

assets
  id
  symbol
  name
  market
  asset_type
  aliases_json
  created_at
  updated_at

signal_assets
  id
  signal_id
  asset_id

signal_tags
  id
  signal_id
  tag
  source

notification_rules
  id
  subscription_id
  ntfy_server
  ntfy_topic
  ntfy_token_encrypted
  min_confidence
  require_asset
  allowed_markets_json
  allowed_stances_json
  enabled
  created_at
  updated_at

notification_events
  id
  signal_id
  notification_rule_id
  status
  error_message
  sent_at
  created_at

crawl_runs
  id
  subscription_id
  status
  started_at
  finished_at
  fetched_count
  inserted_count
  structured_count
  error_message
```

Important constraints:

- Unique `raw_posts(platform, external_id)`.
- Unique `signals(raw_post_id)`.
- `interval_minutes >= 1`.
- Management APIs must never return decrypted API keys or ntfy tokens.

## 7. LLM Structuring And Prompts

The structuring pipeline:

```text
Raw post
  -> pre-detect possible assets
  -> run KOL-specific prompt
  -> validate JSON schema
  -> normalize assets against assets table
  -> store signal and tags
```

Required JSON shape:

```json
{
  "actionable": true,
  "stance": "多 | 空 | 中性 | 无明确观点",
  "assets": [
    {
      "symbol": "SPCX",
      "market": "US_STOCK",
      "asset_type": "stock",
      "name": null
    }
  ],
  "evidence": ["大订单", "技术面", "宏观", "财报", "链上", "消息面"],
  "horizon": "超短线 | 短线 | 中线 | 长线 | 未说明",
  "confidence": "高 | 中 | 低",
  "summary": "一句话总结",
  "risk_notes": "可选风险提示",
  "custom_tags": ["订单流", "突破", "AI链"]
}
```

Prompt rules:

- Provide one global default financial trading prompt.
- Allow each KOL subscription to override the prompt.
- Allow each KOL subscription to bind a model config.
- Provide a management action to suggest a KOL-specific prompt from the KOL's recent posts. The generated prompt is a draft and requires manual save.

Actionable signal definition:

- A signal is actionable when it has a clear asset or market direction and contains at least one of: opinion, evidence, event, or timing context.
- `actionable=false` posts are still stored but hidden from the public homepage by default.

A-share handling:

- V1 recognizes A-share symbols and names in text.
- V1 does not collect A-share social platforms.
- Import or bundle an A-share symbol/name table for normalization.
- The backend should post-process LLM output against `assets` to reduce hallucinated symbols.

## 8. Web Experience

### 8.1 Public Homepage

The homepage is a public read-only market signal tape.

Primary layout:

- Top nav: all signals, US stocks, crypto, A-shares, KOL, assets.
- Left filters: actionable, confidence, stance, market, watchlist.
- Center feed: chronological structured signals.
- Right inspector: session metrics, active notification rules, KOL health.

Signal card content:

- KOL/source avatar
- Title derived from asset + view
- KOL/source and platform
- One-sentence summary
- Tags: stance, asset, market, evidence, horizon, custom tags
- Age, confidence, notification status
- Link to original post

Visual direction:

- Palette: Graphite / Cyan.
- Base: `#101113`, `#17191d`, `#2a2e35`.
- Accent: `#00c2ff`.
- Long: `#37d67a`.
- Short: `#ff5b5b`.
- Text: `#f2f4f8`, muted `#98a3af`.
- Signature element: signal tape vertical accent line on each feed item.

### 8.2 KOL Detail Page

Shows:

- KOL metadata and platform account.
- Recent structured signals.
- Common assets and tags.
- Recent crawl health.
- Prompt summary, visible only in management mode.

### 8.3 Asset Detail Page

Shows:

- Signals grouped by asset.
- KOL stance distribution.
- Recent signal timeline.
- Filters by market, stance, confidence, and source.

### 8.4 Management UI

Requires login.

Management pages:

- Subscriptions: create/edit KOL, platform, handle, interval, prompt, model, enabled state.
- Prompts: global prompt, KOL prompt, suggest prompt from recent posts.
- Models: OpenAI-compatible provider configs.
- Notifications: ntfy server/topic/token and rules.
- Runs: crawl history, failures, retry actions.
- Tests: test crawl, test structuring, test ntfy.

## 9. API Surface

Public read-only API:

```text
GET /api/signals
GET /api/signals/{id}
GET /api/kols
GET /api/kols/{id}
GET /api/assets
GET /api/assets/{symbol}
```

Admin API:

```text
POST /api/admin/login
POST /api/admin/logout
GET /api/admin/me

GET /api/admin/subscriptions
POST /api/admin/subscriptions
PATCH /api/admin/subscriptions/{id}
DELETE /api/admin/subscriptions/{id}

GET /api/admin/model-configs
POST /api/admin/model-configs
PATCH /api/admin/model-configs/{id}
DELETE /api/admin/model-configs/{id}

GET /api/admin/prompts
PATCH /api/admin/prompts/default
POST /api/admin/subscriptions/{id}/suggest-prompt

GET /api/admin/notification-rules
POST /api/admin/notification-rules
PATCH /api/admin/notification-rules/{id}
DELETE /api/admin/notification-rules/{id}

POST /api/admin/subscriptions/{id}/test-crawl
POST /api/admin/subscriptions/{id}/test-structure
POST /api/admin/notification-rules/{id}/test
POST /api/admin/failed-jobs/{id}/retry

GET /api/admin/crawl-runs
GET /api/admin/health
GET /api/admin/notification-events
```

## 10. Docker Deployment

Default Compose services:

```text
web
  Next.js app

api
  FastAPI app with scheduler enabled

redis
  Redis for locks and runtime state

mysql
  Default MySQL service for standalone deployment

playwright-worker
  Optional Binance Square collector runtime
```

Configuration:

- `DATABASE_URL` controls MySQL connection.
- If reusing an existing MySQL instance, disable the Compose `mysql` service and point `DATABASE_URL` to the external database.
- Use a dedicated MySQL database and user. Do not use the root account for the app.
- Store X API credentials, model provider credentials, and ntfy secrets through environment initialization or encrypted admin configuration.

Recommended production deployment:

- Reverse proxy with Caddy or Nginx.
- Public web route for read-only pages.
- Management routes protected by app login.
- Regular MySQL backup.
- Persistent volumes for MySQL and Redis if using Compose-managed services.

## 11. Documentation Plan

Create:

```text
docs/architecture.md
docs/deployment.md
docs/configuration.md
docs/data-sources.md
docs/prompt-guide.md
docs/operations.md
```

Documentation must cover:

- How to deploy with built-in MySQL.
- How to reuse an existing MySQL instance.
- How checkpoint and deduplication work.
- What Binance Square experimental support means.
- How to configure X official API credentials.
- How to configure OpenAI-compatible model providers.
- How ntfy rules are evaluated.
- How to recover from failed crawls, LLM failures, and notification failures.

## 12. Testing And Acceptance Criteria

Collection:

- X subscription fetches new posts by checkpoint and does not duplicate rows.
- Binance Square collector failure does not block X subscriptions.
- Re-running the same crawl does not duplicate raw posts or signals.

Scheduling:

- Per-KOL `interval_minutes` works independently.
- Same KOL cannot run concurrently.
- Service restart preserves checkpoint behavior.

LLM:

- Structured output must pass JSON schema validation.
- Invalid output retries once and then marks failure.
- A-share names and numeric symbols normalize to `assets` when known.

Notification:

- Default ntfy push only triggers for `actionable=true`, qualifying confidence, and rule-matching signals.
- Failed ntfy sends create retryable `notification_events`.

Web:

- Public homepage filters by market, stance, asset, KOL, and confidence.
- Management actions require login.
- Feed cards remain readable on mobile and desktop.
- UI avoids text overlap and keeps stable dimensions for filter controls and signal cards.

Deployment:

- `docker compose up` starts the default stack.
- External MySQL deployment works by changing `DATABASE_URL` and disabling the built-in MySQL service.
- Documentation is sufficient to restore the service from configuration and database backup.

## 13. Risks And Mitigations

X API limits and pricing may constrain minute-level polling.

- Mitigation: per-KOL interval configuration, status visibility, and clear docs.

Binance Square lacks a confirmed stable public read API.

- Mitigation: isolate Playwright collector, mark it experimental, and never let it block the stable X path.

LLM may hallucinate assets or overstate trading direction.

- Mitigation: schema validation, asset normalization, confidence field, and neutral/no-view labels.

Public pages could be mistaken for investment advice.

- Mitigation: phrase content as KOL-derived research signals and avoid direct trade instructions.

## 14. Research References

- X API recent search and user posts documentation: https://docs.x.com/
- Binance developer documentation: https://developers.binance.com/en/docs
- ntfy publish documentation: https://docs.ntfy.sh/publish/
- Product references reviewed for interaction patterns: Kaito, LunarCrush, The Tie, Stocktwits, Fintwit, Zero Terminal, and X Pro/TweetDeck-style column workflows.
