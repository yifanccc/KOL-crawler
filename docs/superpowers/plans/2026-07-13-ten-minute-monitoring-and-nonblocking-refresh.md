# 10 分钟监控与非阻断刷新 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Collector 和订阅默认调度统一为 10 分钟，固定新增订阅的 Serenity 提示词快照，并消除后台刷新期间的页面阻断。

**Architecture:** 后端以版本化常量提供新增订阅的间隔和提示词默认值，前端从 `config-options` 读取这些默认值。Collector 的配置循环独立改为 600 秒。前端用一个可测试的刷新策略区分首次加载和已有数据后的后台刷新，后台失败保留最后一次成功数据。

**Tech Stack:** FastAPI、SQLAlchemy、Pydantic、Next.js 15、React 19、TypeScript、Node test runner、Python pytest、macOS launchd、Docker Compose。

## Global Constraints

- 不使用 subagent，不创建 worktree，在当前工作树串行执行。
- Collector `CONFIG_POLL_SECONDS` 默认值固定为 `600`。
- 所有未删除生产订阅的 `interval_minutes` 更新为 `10`。
- Dashboard 数据刷新仍保持 `60_000` 毫秒，但后台刷新不得替换已有内容。
- 新增订阅使用 2026-07-13 生产 Serenity 提示词的固定快照，不动态查询 Serenity。
- 继续使用服务器端 production Compose 在线构建，Python 包源使用腾讯云镜像。
- 不修改 checkpoint、历史帖子、信号、现有订阅提示词、MySQL/Redis volume 或 Nginx。
- 当前仓库基线大部分文件未纳入 Git；不自动 stage 或 commit，避免混入用户现有工作。

---

### Task 1: 后端 10 分钟默认值与固定提示词

**Files:**
- Modify: `backend/app/models/subscription.py`
- Modify: `backend/app/services/structurer.py`
- Modify: `backend/app/services/bootstrap.py`
- Modify: `backend/app/routers/admin.py`
- Modify: `backend/tests/test_admin.py`

**Interfaces:**
- Produces: `DEFAULT_MONITOR_INTERVAL_MINUTES: int = 10`
- Produces: `SubscriptionCreate.intervalMinutes` 默认值 10
- Produces: `GET /api/admin/config-options.defaultIntervalMinutes`
- Produces: 创建订阅省略提示词时持久化 `DEFAULT_SYSTEM_PROMPT`、`DEFAULT_USER_PROMPT` 和 `DEFAULT_OUTPUT_SCHEMA`

- [x] **Step 1: 写后端失败测试**

在 `backend/tests/test_admin.py` 增加测试，创建请求只发送平台和 handle：

```python
def test_new_subscription_uses_ten_minute_and_fixed_prompt_defaults() -> None:
    reset_database()
    with TestClient(app) as client:
        headers = auth_headers(client)
        options = client.get("/api/admin/config-options", headers=headers)
        created = client.post(
            "/api/admin/subscriptions",
            headers=headers,
            json={"platform": "x", "handle": "new-defaults"},
        )

    assert options.status_code == 200
    assert options.json()["defaultIntervalMinutes"] == 10
    assert created.status_code == 200
    item = created.json()["item"]
    assert item["intervalMinutes"] == 10
    assert item["systemPrompt"] == DEFAULT_SYSTEM_PROMPT
    assert item["userPrompt"] == DEFAULT_USER_PROMPT
    assert item["outputSchema"] == DEFAULT_OUTPUT_SCHEMA
    assert "内容简洁，不需要增加作者认为" in item["systemPrompt"]
```

- [x] **Step 2: 运行测试并确认 RED**

Run:

```bash
docker cp backend/app/. kol-crawler-api-1:/tmp/kol-backend/app
docker cp backend/tests/. kol-crawler-api-1:/tmp/kol-backend/tests
docker exec -e PYTHONPATH=/tmp/kol-backend kol-crawler-api-1 \
  pytest -q /tmp/kol-backend/tests/test_admin.py \
  -k new_subscription_uses_ten_minute_and_fixed_prompt_defaults
```

Expected: FAIL。实际 RED 为 config-options 不含 `defaultIntervalMinutes`，测试读取该字段时得到 `KeyError`。

- [x] **Step 3: 实现固定后端默认值**

在 `backend/app/models/subscription.py` 定义并使用：

```python
DEFAULT_MONITOR_INTERVAL_MINUTES = 10

interval_minutes: Mapped[int] = mapped_column(
    Integer,
    nullable=False,
    default=DEFAULT_MONITOR_INTERVAL_MINUTES,
)
```

把 `backend/app/services/structurer.py` 的 `DEFAULT_SYSTEM_PROMPT` 更新为生产 Serenity 当前文本，保留现有 User prompt 和 Output Schema，并补齐：

```text
4. key_points 最多 5 条，但不用强制凑满 5 条，只保留原文可验证的依据。
8. 内容简洁，不需要增加作者认为，作者表示之类的说明。
```

在 `SubscriptionCreate` 中把 `intervalMinutes` 改为：

```python
intervalMinutes: int = Field(default=DEFAULT_MONITOR_INTERVAL_MINUTES, ge=1)
```

创建或恢复订阅前解析固定默认值：

```python
system_prompt = payload.systemPrompt or DEFAULT_SYSTEM_PROMPT
user_prompt = payload.userPrompt or DEFAULT_USER_PROMPT
output_schema = payload.outputSchema or DEFAULT_OUTPUT_SCHEMA
```

新建和恢复路径都持久化这三个解析后的值，并把 `prompt_version` 设为 `custom-v1`。`config_options` 增加：

```python
"defaultIntervalMinutes": DEFAULT_MONITOR_INTERVAL_MINUTES,
```

`ensure_defaults` 创建默认订阅时也使用 `DEFAULT_MONITOR_INTERVAL_MINUTES`。

- [x] **Step 4: 运行目标测试和后端全量测试**

Run:

```bash
docker cp backend/app/. kol-crawler-api-1:/tmp/kol-backend/app
docker cp backend/tests/. kol-crawler-api-1:/tmp/kol-backend/tests
docker exec -e PYTHONPATH=/tmp/kol-backend kol-crawler-api-1 \
  pytest -q /tmp/kol-backend/tests/test_admin.py \
  -k new_subscription_uses_ten_minute_and_fixed_prompt_defaults
docker exec -e PYTHONPATH=/tmp/kol-backend kol-crawler-api-1 \
  pytest -q /tmp/kol-backend/tests
```

Expected: 目标测试 PASS；后端全量测试 0 failures。

---

### Task 2: Collector 600 秒循环

**Files:**
- Create: `collector/tests/test_config.py`
- Modify: `collector/collector_agent/config.py`
- Modify: `collector/.env.example`
- Modify: `collector/.env`

**Interfaces:**
- Produces: `CollectorSettings.from_env().config_poll_seconds == 600` when unset
- Consumes: 订阅 API 返回的 `intervalMinutes=10`

- [x] **Step 1: 写 Collector 失败测试**

新增 `collector/tests/test_config.py`：

```python
from collector_agent.config import CollectorSettings


def test_config_poll_defaults_to_ten_minutes(monkeypatch, tmp_path):
    monkeypatch.setenv("PUBLIC_API_URL", "http://example.test/kol")
    monkeypatch.setenv("COLLECTOR_AGENT_ID", "home")
    monkeypatch.setenv("COLLECTOR_TOKEN", "token")
    monkeypatch.setenv("COLLECTOR_DB_PATH", str(tmp_path / "collector.sqlite3"))
    monkeypatch.delenv("CONFIG_POLL_SECONDS", raising=False)

    settings = CollectorSettings.from_env()

    assert settings.config_poll_seconds == 600
```

- [x] **Step 2: 运行并确认 RED**

Run:

```bash
PYTHONPATH=collector pytest -q collector/tests/test_config.py
```

Expected: FAIL，当前值为 60。

- [x] **Step 3: 改为 600 秒**

在 `collector/collector_agent/config.py` 同时修改 dataclass 默认值和环境变量 fallback：

```python
config_poll_seconds: int = 600
config_poll_seconds=max(1, int(os.environ.get("CONFIG_POLL_SECONDS", "600")))
```

把 `collector/.env.example` 和本机 `collector/.env` 的 `CONFIG_POLL_SECONDS` 改为 `600`。

- [x] **Step 4: 运行 Collector 全量测试**

Run:

```bash
PYTHONPATH=collector pytest -q collector/tests
```

Expected: 0 failures。

---

### Task 3: 前端新增默认值与非阻断刷新

**Files:**
- Create: `frontend/src/lib/refreshPolicy.ts`
- Create: `frontend/tests/refreshPolicy.test.mjs`
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/components/AdminShell.tsx`
- Modify: `frontend/src/app/page.tsx`
- Modify: `frontend/src/lib/useMarketData.ts`

**Interfaces:**
- Produces: `isBlockingRefresh(hasLoaded: boolean): boolean`
- Consumes: `AdminConfigOptions.defaultIntervalMinutes`

- [x] **Step 1: 写刷新策略失败测试**

新增 `frontend/tests/refreshPolicy.test.mjs`，在模块不存在时用旧行为作为 fallback，从而得到明确断言失败：

```javascript
import assert from "node:assert/strict";
import test from "node:test";

const policy = await import("../src/lib/refreshPolicy.ts").catch(() => ({
  isBlockingRefresh: () => true,
}));

test("initial load is blocking", () => {
  assert.equal(policy.isBlockingRefresh(false), true);
});

test("refresh after successful data load is non-blocking", () => {
  assert.equal(policy.isBlockingRefresh(true), false);
});

test("background refresh failure preserves existing content", () => {
  const error = policy.refreshErrorMessage?.(true, "request failed") ?? "request failed";
  assert.equal(error, "");
});
```

- [x] **Step 2: 运行并确认 RED**

Run:

```bash
cd frontend && node --experimental-strip-types --test tests/refreshPolicy.test.mjs
```

Expected: 第二个测试 FAIL，实际值为 true。

- [x] **Step 3: 实现刷新策略**

新增 `frontend/src/lib/refreshPolicy.ts`：

```typescript
export function isBlockingRefresh(hasLoaded: boolean): boolean {
  return !hasLoaded;
}
```

在首页和 `useMarketData` 中增加 `useRef(false)`。每次加载前计算：

```typescript
const blocking = isBlockingRefresh(hasLoadedRef.current);
if (blocking) {
  setLoading(true);
  setError("");
}
```

成功后执行：

```typescript
hasLoadedRef.current = true;
setError("");
```

失败时通过 `refreshErrorMessage` 区分首次加载与后台刷新；finally 只在 `blocking` 为 true 时关闭 Loading。定时器仍为 `60_000`。

最终实现增加 `refreshErrorMessage(hasLoaded, message)`：首次加载失败返回错误文本，已有成功数据后的后台刷新失败返回空字符串，确保旧内容继续可用。

- [x] **Step 4: 接入 10 分钟表单默认值**

给 `AdminConfigOptions` 增加：

```typescript
defaultIntervalMinutes: number;
```

API normalization 使用服务端字段，兼容 fallback 10：

```typescript
defaultIntervalMinutes: numberValue(json.defaultIntervalMinutes) ?? 10,
```

`newForm` 使用：

```typescript
intervalMinutes: String(options.defaultIntervalMinutes),
```

提交时无效输入 fallback 也改为 10：

```typescript
intervalMinutes: Math.max(1, Number(form.intervalMinutes) || 10),
```

- [x] **Step 5: 运行前端测试和 production build**

Run:

```bash
cd frontend
node --experimental-strip-types --test tests/refreshPolicy.test.mjs
npm run build
```

Expected: 三个策略测试 PASS；Next.js production build exit 0。

---

### Task 4: 文档、生产数据与部署验收

**Files:**
- Modify: `docs/configuration.md`
- Modify: `docs/operations.md`
- Modify: `docs/verification.md`
- Modify: `docs/superpowers/plans/2026-07-13-ten-minute-monitoring-and-nonblocking-refresh.md`

**Interfaces:**
- Consumes: 后端 API、Web 构建产物和本机 Collector 配置
- Produces: 生产所有未删除订阅 10 分钟、健康 Collector、可用 Dashboard

- [x] **Step 1: 更新运维文档**

记录：

- `CONFIG_POLL_SECONDS=600`
- 新增订阅默认 10 分钟
- Dashboard 每 60 秒非阻断刷新
- 新增提示词是 Serenity 2026-07-13 固定快照
- 检查命令：

```bash
./scripts/collector-status.sh
./scripts/collector-logs.sh --lines 100
```

- [x] **Step 2: 同步源码并在线构建**

只同步本轮变更，不能覆盖服务器 `.env`：

```bash
rsync -avR --checksum \
  backend/app/models/subscription.py \
  backend/app/services/structurer.py \
  backend/app/services/bootstrap.py \
  backend/app/routers/admin.py \
  backend/app/main.py \
  backend/tests/test_admin.py \
  backend/tests/test_main.py \
  collector/collector_agent/config.py \
  collector/.env.example \
  collector/tests/test_config.py \
  frontend/src/lib/refreshPolicy.ts \
  frontend/tests/refreshPolicy.test.mjs \
  frontend/src/lib/types.ts \
  frontend/src/lib/api.ts \
  frontend/src/components/AdminShell.tsx \
  frontend/src/app/page.tsx \
  frontend/src/lib/useMarketData.ts \
  docs/configuration.md \
  docs/operations.md \
  docs/verification.md \
  deploy@www.yifanlab.cloud:/home/deploy/kol-crawler/
```

在服务器使用腾讯云镜像执行：

```bash
cd /home/deploy/kol-crawler
docker compose --env-file .env -f deploy/docker-compose.prod.yml build api web
```

- [x] **Step 3: 更新生产订阅间隔**

在 API 切换前记录当前值，然后执行幂等更新：

```sql
SELECT id, platform, platform_handle, interval_minutes
FROM subscriptions
WHERE deleted_at IS NULL
ORDER BY id;

UPDATE subscriptions
SET interval_minutes = 10
WHERE deleted_at IS NULL;
```

再次 SELECT，要求所有返回行均为 10。

- [x] **Step 4: 只重建 API 与 Web**

```bash
docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  up -d --no-deps api web
```

验证：

```bash
curl -fsS http://127.0.0.1:18010/health
curl -fsS -o /dev/null http://127.0.0.1:13010/kol/login
docker compose --env-file .env -f deploy/docker-compose.prod.yml ps
```

- [x] **Step 5: 重启并验证本机 Collector**

```bash
./scripts/collector-stop.sh
./scripts/collector-start.sh
./scripts/collector-status.sh
./scripts/collector-logs.sh --lines 100
```

要求首轮每个订阅有 `status=success` 或明确 `failed`，下一次正常抓取时间按 10 分钟推进，heartbeat 中 X 为 `authenticated`、Binance 为 `healthy`、Outbox 为 0。

- [ ] **Step 6: 浏览器验收**

在已登录的 Dashboard：

1. 打开首页并确认已有信号卡片可见。
2. 等待或触发一次 60 秒数据刷新。
3. 确认刷新期间卡片、筛选和导航始终可见，不出现全屏 Loading。
4. 打开 KOL 页、标的页和 Admin 页，重复验证。
5. 新建订阅表单默认显示 10 分钟和固定 Serenity 提示词。
6. 检查浏览器控制台无新增 error/warning。

当前独立浏览器会话没有管理员登录态；已完成未认证入口、登录页、横向溢出和控制台烟测。认证后的刷新行为由策略测试、production build 与生产 API 日志验证，保留为人工登录后的最终观察项。

- [x] **Step 7: 最终全量验证**

```bash
docker exec -e PYTHONPATH=/tmp/kol-backend kol-crawler-api-1 \
  pytest -q /tmp/kol-backend/tests
PYTHONPATH=collector pytest -q collector/tests
cd frontend && npm run build
```

Expected: 所有命令 exit 0；生产 API/Web 健康；现有订阅均为 10 分钟；Collector 运行且页面后台刷新不阻断。

---

### Task 5: API 分析非阻塞与模型快速切换

**Files:**
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_main.py`
- Modify: `.env`（私有配置，不同步进 Git）
- Modify: 生产 `/home/deploy/kol-crawler/.env`

**Interfaces:**
- Produces: `process_analysis_batch()`
- Produces: `analysis_loop()` 通过 `asyncio.to_thread` 执行同步数据库与模型分析
- Consumes: `OPENAI_MODEL=gpt-5.6-terra`

- [x] **Step 1: 复现事件循环阻塞**

用 0.2 秒同步分析替身运行 `analysis_loop`。RED 结果为事件循环延迟 0.2016 秒，证明模型分析会阻塞 Dashboard API。

- [x] **Step 2: 在线程内创建 Session 并执行分析**

把 Session 创建、`process_pending_posts` 和 Session 关闭封装为 `process_analysis_batch()`，从异步循环调用：

```python
await asyncio.to_thread(process_analysis_batch)
```

目标测试 GREEN；部署镜像内复测事件循环延迟 0.0105 秒。

- [x] **Step 3: 全量测试并发布 API**

后端全量结果为 54 passed、1 条既有 Starlette 弃用警告。服务器使用腾讯云 PyPI 镜像在线构建 API，只重建 API 容器；回滚镜像标签为 `kol-crawler-api:rollback-before-nonblocking-analysis`。

- [x] **Step 4: 快速切换生产模型**

本机和生产 `OPENAI_MODEL` 均设置为 `gpt-5.6-terra`。生产 `.env` 先备份为 `.env.before-openai-model-20260714003213`，然后只执行 `up -d --no-deps --force-recreate api`，没有重新 build。

- [x] **Step 5: 验证 Collector 恢复**

旧 API 阻塞期间的一次 heartbeat 出现 `ConnectTimeout`，但新帖已生成 Signal 且 Outbox 为 0。并发修复后的下一轮 7 个订阅全部成功，heartbeat 恢复为 healthy，X `authenticated`、Binance Square `healthy`、Outbox 0。
