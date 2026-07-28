# Signal Totals and Actionable Filtering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. The user explicitly prohibited subagents. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the real signal count, apply dashboard filters before pagination, and let users toggle “仅可执行” from either the filter bar or the actionable statistic card.

**Architecture:** Extend `GET /api/signals` additively with pagination and exact count metadata while moving filters into SQL. Keep `fetchSignals()` backward compatible and add `fetchSignalPage()` for the dashboard. Store actionable state with the other dashboard filters, then render a synchronized select and accessible statistic-card button.

**Tech Stack:** FastAPI, SQLAlchemy 2, pytest, Next.js 15, React 19, TypeScript, Node test runner, existing Graphite/Cyan CSS.

**Status:** Completed and deployed on 2026-07-20. Production verification: 124 total signals, 100 on the first page, 24 on the second page, and 32 actionable signals.

## Global Constraints

- Keep the existing `items` response field and existing query parameter meanings.
- Default pagination is `limit=100`, `offset=0`; enforce `1 <= limit <= 100` and `offset >= 0`.
- Preserve `RawPost.published_at DESC, Signal.id DESC` ordering.
- Do not change Collector, Agnes, ntfy, authentication, database tables, or the ten-minute schedule.
- Match the existing statistic cards and filter-bar visual language.
- Do not stage or commit pre-existing untracked source files; the shared worktree already contains user-owned untracked implementation.

---

### Task 1: Add backend regression coverage for counts, pagination, and pre-pagination filtering

**Files:**
- Modify: `backend/tests/test_public_api.py`

**Interfaces:**
- Consumes: authenticated `GET /api/signals`.
- Produces: regression expectations for `total`, `overallTotal`, `actionableTotal`, `limit`, `offset`, and `actionable=true`.

- [x] **Step 1: Add a reusable 105-signal fixture helper**

Add imports for `timedelta`, then add:

```python
def seed_paginated_signals() -> None:
    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    with SessionLocal.begin() as session:
        for index in range(105):
            raw_post = RawPost(
                platform="x",
                external_id=f"page-{index}",
                published_at=base + timedelta(minutes=index),
                raw_text=f"post {index}",
            )
            session.add(raw_post)
            session.flush()
            session.add(
                Signal(
                    raw_post_id=raw_post.id,
                    actionable=index == 0,
                    stance="bullish" if index == 0 else "neutral",
                    summary=f"signal {index}",
                    importance=5 if index == 0 else 1,
                )
            )
```

- [x] **Step 2: Write three failing endpoint tests**

```python
def test_signals_endpoint_returns_true_totals_and_pagination() -> None:
    reset_database()
    seed_paginated_signals()
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "testadmin", "password": "test-admin-password"})
        first = client.get("/api/signals")
        tail = client.get("/api/signals", params={"limit": 5, "offset": 100})
    assert first.status_code == 200
    assert len(first.json()["items"]) == 100
    assert {key: first.json()[key] for key in ("total", "overallTotal", "actionableTotal", "limit", "offset")} == {
        "total": 105,
        "overallTotal": 105,
        "actionableTotal": 1,
        "limit": 100,
        "offset": 0,
    }
    assert [item["summary"] for item in tail.json()["items"]] == [
        "signal 4", "signal 3", "signal 2", "signal 1", "signal 0"
    ]


def test_actionable_filter_runs_before_pagination() -> None:
    reset_database()
    seed_paginated_signals()
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "testadmin", "password": "test-admin-password"})
        response = client.get("/api/signals", params={"actionable": "true"})
    assert response.status_code == 200
    assert [item["summary"] for item in response.json()["items"]] == ["signal 0"]
    assert response.json()["total"] == 1
    assert response.json()["overallTotal"] == 105
    assert response.json()["actionableTotal"] == 1


def test_signals_endpoint_validates_pagination_bounds() -> None:
    reset_database()
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "testadmin", "password": "test-admin-password"})
        responses = [
            client.get("/api/signals", params={"limit": 0}),
            client.get("/api/signals", params={"limit": 101}),
            client.get("/api/signals", params={"offset": -1}),
        ]
    assert [response.status_code for response in responses] == [422, 422, 422]
```

- [x] **Step 3: Run the targeted tests and verify RED**

Run:

```bash
cd backend
pytest -q tests/test_public_api.py -k "true_totals or before_pagination or pagination_bounds"
```

Expected: failures because metadata is absent, the old actionable filter cannot see `signal 0`, and invalid pagination parameters are currently ignored.

---

### Task 2: Implement the filtered, paginated signal query

**Files:**
- Modify: `backend/app/routers/public.py`
- Test: `backend/tests/test_public_api.py`

**Interfaces:**
- Consumes: `kol_id`, `asset`/`symbol`, `tag`, `stance`, `actionable`, `platform`, `time_range`, `min_importance`, `limit`, `offset`.
- Produces: `{items, total, overallTotal, actionableTotal, limit, offset}`.

- [x] **Step 1: Add boundary types and query helpers**

Import `timedelta`, `Literal`, `Query`, `exists`, `func`, and `Subscription`. Define:

```python
TIME_RANGE_HOURS = {"1h": 1, "6h": 6, "24h": 24, "7d": 24 * 7}


def _count_query(db: Session, query) -> int:
    return int(db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0)


def _filtered_signals_query(
    *,
    kol_id: int | None,
    platform: str | None,
    requested_asset: str | None,
    tag: str | None,
    stance: str | None,
    time_range: str,
    min_importance: int,
):
    query = select(Signal).join(RawPost, RawPost.id == Signal.raw_post_id)
    if kol_id is not None:
        query = query.where(
            exists(
                select(1).where(
                    Subscription.id == Signal.subscription_id,
                    Subscription.kol_profile_id == kol_id,
                )
            )
        )
    if platform:
        query = query.where(func.lower(RawPost.platform) == platform.lower())
    if requested_asset:
        normalized_asset = requested_asset.lstrip("$").upper()
        query = query.where(
            exists(
                select(1)
                .select_from(SignalAsset)
                .join(Asset, Asset.id == SignalAsset.asset_id)
                .where(
                    SignalAsset.signal_id == Signal.id,
                    func.upper(Asset.symbol) == normalized_asset,
                )
            )
        )
    if tag:
        query = query.where(
            exists(select(1).where(SignalTag.signal_id == Signal.id, SignalTag.tag == tag))
        )
    if stance:
        normalized_stance = {
            "long": "bullish",
            "short": "bearish",
            "neutral": "neutral",
            "watch": "neutral",
            "unknown": "unclear",
            "多": "bullish",
            "空": "bearish",
            "中性": "neutral",
            "不明确": "unclear",
        }.get(stance, stance)
        query = query.where(Signal.stance == normalized_stance)
    if time_range != "all":
        query = query.where(
            RawPost.published_at >= datetime.now(UTC) - timedelta(hours=TIME_RANGE_HOURS[time_range])
        )
    if min_importance > 1:
        query = query.where(func.coalesce(Signal.importance, 1) >= min_importance)
    return query
```

- [x] **Step 2: Replace post-fetch filtering with SQL filtering**

Extend `list_signals()` with:

```python
platform: str | None = None,
time_range: Literal["all", "1h", "6h", "24h", "7d"] = "all",
min_importance: int = Query(default=1, ge=1, le=5),
limit: int = Query(default=100, ge=1, le=100),
offset: int = Query(default=0, ge=0),
```

Build the base query without `actionable`, calculate:

```python
overall_total = int(db.scalar(select(func.count(Signal.id))) or 0)
actionable_total = _count_query(db, base_query.where(Signal.actionable.is_(True)))
filtered_query = (
    base_query.where(Signal.actionable.is_(actionable))
    if actionable is not None
    else base_query
)
total = _count_query(db, filtered_query)
signals = db.scalars(
    filtered_query
    .order_by(desc(RawPost.published_at), desc(Signal.id))
    .offset(offset)
    .limit(limit)
).all()
return {
    "items": [_signal_payload(db, signal) for signal in signals],
    "total": total,
    "overallTotal": overall_total,
    "actionableTotal": actionable_total,
    "limit": limit,
    "offset": offset,
}
```

Delete the old in-memory KOL, asset, stance, actionable, and tag filters.

- [x] **Step 3: Run targeted and full backend verification**

Run:

```bash
cd backend
pytest -q tests/test_public_api.py
pytest -q
```

Expected: all tests pass.

---

### Task 3: Add the typed frontend page contract and request serialization

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/tests/signalPage.test.mjs`

**Interfaces:**
- Produces: `SignalQuery`, `SignalPage`, `buildSignalQuery()`, and `fetchSignalPage()`.
- Preserves: `fetchSignals(params): Promise<Signal[]>`.

- [x] **Step 1: Write the failing frontend contract test**

Create:

```javascript
import assert from "node:assert/strict";
import test from "node:test";

const api = await import("../src/lib/api.ts");

test("signal query serializes filters and pagination", () => {
  const query = api.buildSignalQuery({
    kolId: "7",
    platform: "X",
    symbol: "NVDA",
    tag: "AI",
    stance: "long",
    actionable: true,
    timeRange: "24h",
    minImportance: 3,
    limit: 25,
    offset: 50,
  });
  assert.equal(
    query,
    "kol_id=7&platform=X&symbol=NVDA&tag=AI&stance=long&actionable=true&time_range=24h&min_importance=3&limit=25&offset=50",
  );
});
```

- [x] **Step 2: Run the Node test and verify RED**

Run:

```bash
cd frontend
node --test tests/signalPage.test.mjs
```

Expected: FAIL because `buildSignalQuery` does not exist.

- [x] **Step 3: Define additive types**

In `frontend/src/lib/types.ts`, add:

```typescript
export interface SignalQuery {
  kolId?: string;
  platform?: string;
  symbol?: string;
  tag?: string;
  stance?: string;
  actionable?: boolean;
  timeRange?: string;
  minImportance?: number;
  limit?: number;
  offset?: number;
}

export interface SignalPage {
  items: Signal[];
  total: number;
  overallTotal: number;
  actionableTotal: number;
  limit: number;
  offset: number;
}
```

- [x] **Step 4: Implement serialization and compatibility**

Export `buildSignalQuery(params: SignalQuery = {}): string`, adding parameters in the exact order asserted by the test. Add:

```typescript
export async function fetchSignalPage(params: SignalQuery = {}): Promise<SignalPage> {
  const query = buildSignalQuery(params);
  const json = await getJson(`/api/signals${query ? `?${query}` : ""}`);
  const items = normalizeItems(json).map(normalizeSignal);
  const source = isRecord(json) ? json : {};
  const total = numberValue(source.total) ?? items.length;
  return {
    items,
    total,
    overallTotal: numberValue(source.overallTotal) ?? total,
    actionableTotal:
      numberValue(source.actionableTotal) ?? items.filter((signal) => signal.actionable).length,
    limit: numberValue(source.limit) ?? params.limit ?? 100,
    offset: numberValue(source.offset) ?? params.offset ?? 0,
  };
}

export async function fetchSignals(params: SignalQuery = {}): Promise<Signal[]> {
  return (await fetchSignalPage(params)).items;
}
```

- [x] **Step 5: Run the frontend contract test and type checker**

Run:

```bash
cd frontend
node --test tests/*.test.mjs
npx tsc --noEmit
```

Expected: all Node tests pass and TypeScript exits 0.

---

### Task 4: Add synchronized actionable filter state

**Files:**
- Create: `frontend/src/lib/dashboardFilters.ts`
- Create: `frontend/tests/dashboardFilters.test.mjs`
- Modify: `frontend/src/components/FilterBar.tsx`

**Interfaces:**
- Produces: `DashboardFilters`, `defaultDashboardFilters`, `toggleActionableOnly()`.
- Consumes: the same filter object from the homepage and FilterBar.

- [x] **Step 1: Write a failing state test**

```javascript
import assert from "node:assert/strict";
import test from "node:test";

const filters = await import("../src/lib/dashboardFilters.ts");

test("actionable filter toggles and resets", () => {
  assert.equal(filters.defaultDashboardFilters.actionableOnly, false);
  const enabled = filters.toggleActionableOnly(filters.defaultDashboardFilters);
  assert.equal(enabled.actionableOnly, true);
  assert.equal(filters.toggleActionableOnly(enabled).actionableOnly, false);
});
```

- [x] **Step 2: Run the test and verify RED**

Run:

```bash
cd frontend
node --test tests/dashboardFilters.test.mjs
```

Expected: FAIL because `dashboardFilters.ts` does not exist.

- [x] **Step 3: Implement the filter state module**

Move the existing filter type/default values into `frontend/src/lib/dashboardFilters.ts` and add:

```typescript
export function toggleActionableOnly(filters: DashboardFilters): DashboardFilters {
  return { ...filters, actionableOnly: !filters.actionableOnly };
}
```

- [x] **Step 4: Add the FilterBar control**

Import `DashboardFilters` from `@/lib/dashboardFilters`, remove the local interface, and add:

```tsx
<label>
  <span>执行性</span>
  <select
    value={filters.actionableOnly ? "true" : ""}
    onChange={(event) =>
      onChange(patchFilters(filters, { actionableOnly: event.target.value === "true" }))
    }
  >
    <option value="">全部</option>
    <option value="true">仅可执行</option>
  </select>
</label>
```

- [x] **Step 5: Run the state test and type checker**

Run:

```bash
cd frontend
node --test tests/*.test.mjs
npx tsc --noEmit
```

Expected: all pass.

---

### Task 5: Wire exact totals, pagination, and the statistic-card shortcut into the homepage

**Files:**
- Modify: `frontend/src/components/StatCard.tsx`
- Modify: `frontend/src/app/page.tsx`
- Modify: `frontend/src/app/globals.css`

**Interfaces:**
- Consumes: `SignalPage`, `DashboardFilters`, `toggleActionableOnly()`.
- Produces: synchronized actionable select/card, exact totals, and previous/next pagination.

- [x] **Step 1: Make StatCard optionally interactive**

Add optional `active` and `onClick` props. Render a native button only when `onClick` exists:

```tsx
const className = `stat-card stat-card-${tone}${active ? " stat-card-active" : ""}`;
const content = (
  <>
    <div><span>{label}</span><strong>{value}</strong></div>
    <Icon size={18} aria-hidden="true" />
    {detail ? <p>{detail}</p> : null}
  </>
);
return onClick ? (
  <button type="button" className={`${className} stat-card-interactive`} aria-pressed={active} onClick={onClick}>
    {content}
  </button>
) : (
  <article className={className}>{content}</article>
);
```

- [x] **Step 2: Replace client-only result counting with SignalPage metadata**

In the homepage:

- Import `fetchSignalPage`, `defaultDashboardFilters`, and `toggleActionableOnly`.
- Track `{total, overallTotal, actionableTotal, limit, offset}` and page offset.
- Call `fetchSignalPage()` with every dashboard filter and `actionable: true` only when `actionableOnly` is enabled.
- Reset offset to zero whenever filters change.
- Use returned `items` directly; keep active-symbol and long/short calculations scoped to the visible page.

Use:

```tsx
<StatCard
  icon={Activity}
  label="实时情报"
  value={signalPage.total}
  detail={`${signalPage.overallTotal} 条总样本`}
/>
<StatCard
  icon={BellRing}
  label="可执行"
  value={signalPage.actionableTotal}
  detail={filters.actionableOnly ? "正在仅显示可执行信号" : "观点 + 标的 + 依据"}
  tone="long"
  active={filters.actionableOnly}
  onClick={() => applyFilters(toggleActionableOnly(filters))}
/>
```

- [x] **Step 3: Add pagination controls**

Show `0 / 0` for no matches, otherwise `${offset + 1}-${offset + items.length} / ${total}`. Add two icon buttons with explicit labels:

```tsx
<button type="button" aria-label="上一页" disabled={offset === 0} onClick={showPreviousPage}>
  <ChevronLeft size={15} aria-hidden="true" />
</button>
<button
  type="button"
  aria-label="下一页"
  disabled={offset + signalPage.limit >= signalPage.total}
  onClick={showNextPage}
>
  <ChevronRight size={15} aria-hidden="true" />
</button>
```

- [x] **Step 4: Add style-consistent interaction states**

Add CSS using existing tokens:

```css
button.stat-card {
  width: 100%;
  color: inherit;
  text-align: left;
}

.stat-card-interactive:hover {
  border-color: rgba(32, 201, 151, 0.5);
}

.stat-card-interactive.stat-card-active {
  border-color: rgba(32, 201, 151, 0.72);
  background: var(--long-soft);
}

.feed-pagination {
  display: flex;
  align-items: center;
  gap: 6px;
}
```

Style pagination buttons with the existing panel, line, radius, hover, focus, and disabled tokens. Do not introduce new colors or radii.

- [x] **Step 5: Run frontend tests and production build**

Run:

```bash
cd frontend
node --test tests/*.test.mjs
npx tsc --noEmit
npm run build
```

Expected: all tests pass, type checking exits 0, and Next build succeeds.

---

### Task 6: End-to-end verification and production handoff

**Files:**
- Verify only; no additional source files unless a test exposes a defect.

**Interfaces:**
- Verifies: backend response, local browser interaction, responsive layout, and production deployment readiness.

- [x] **Step 1: Run full repository tests**

```bash
cd backend && pytest -q
cd ../frontend && node --test tests/*.test.mjs && npx tsc --noEmit && npm run build
```

- [x] **Step 2: Run local authenticated API checks**

Verify a database with more than 100 rows returns:

- `overallTotal > 100`
- `items.length <= 100`
- `actionable=true` returns only actionable items
- invalid `limit`/`offset` returns 422

- [x] **Step 3: Inspect the homepage in a real browser**

At desktop and narrow mobile widths:

- Confirm total sample is greater than 100 when the database is.
- Toggle “仅可执行” from the select and from the card.
- Confirm both controls stay synchronized.
- Confirm `aria-pressed` changes and keyboard activation works.
- Confirm pagination moves to the next page and preserves published-time ordering.
- Confirm no console errors, overflow, or visual mismatch.

- [x] **Step 4: Review the exact worktree diff**

Run:

```bash
git diff --check
git status --short
```

Confirm only the files named in this plan were modified by this task. Do not stage the pre-existing untracked application tree.

- [x] **Step 5: Deploy only within the established production workflow**

If production deployment remains authorized in the active conversation, sync only the changed source files to `/home/deploy/kol-crawler`, build with `deploy/docker-compose.prod.yml` and Tencent PyPI mirror, recreate only `api` and `web`, then re-run authenticated external API and browser checks. Otherwise stop after local verification and report the exact deploy commands.
