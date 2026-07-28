# Collector Configurable Catch-up Limit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Collector 在已有 checkpoint 时补抓最近最多 5 条新帖，并允许通过环境变量调整上限。

**Architecture:** `CollectorSettings` 提供独立的 `catchup_fetch_limit`，`CollectorScheduler` 根据 checkpoint 是否存在选择首次初始化或停机补抓上限。Provider 继续负责 checkpoint 过滤和时间排序，并在边界处再次限制返回数量；Outbox/checkpoint 原子写入和上传重试保持不变。

**Tech Stack:** Python 3.12、pytest、SQLite、OpenCLI、Binance Square browser provider、macOS launchd。

## Global Constraints

- 不使用 subagent，不创建 worktree，在当前工作树串行执行。
- `INITIAL_FETCH_LIMIT` 默认保持 1。
- `CATCHUP_FETCH_LIMIT` 默认是 5，最小值是 1。
- 超过上限时只保留最新帖子，按旧到新写入 Outbox。
- 不修改公网 API、生产数据库、现有 checkpoint、历史帖子、信号、MySQL/Redis、Web 或 Nginx。
- 当前仓库大部分文件未纳入 Git，不自动 stage 或 commit。

---

### Task 1: 配置与 Scheduler 补抓上限

**Files:**
- Modify: `collector/tests/test_config.py`
- Modify: `collector/tests/test_scheduler.py`
- Modify: `collector/collector_agent/config.py`
- Modify: `collector/collector_agent/scheduler.py`
- Modify: `collector/collector_agent/main.py`

**Interfaces:**
- Produces: `CollectorSettings.catchup_fetch_limit: int`
- Produces: `CollectorScheduler(..., catchup_fetch_limit: int = 5)`

- [x] **Step 1: 写配置和 Scheduler 失败测试**

```python
def test_catchup_fetch_defaults_to_five(monkeypatch, tmp_path):
    # 设置必需环境变量并删除 CATCHUP_FETCH_LIMIT
    settings = CollectorSettings.from_env()
    assert settings.catchup_fetch_limit == 5


def test_scheduler_uses_initial_then_configurable_catchup_limit(tmp_path):
    scheduler = CollectorScheduler(
        store,
        api,
        {"x": provider},
        initial_fetch_limit=1,
        catchup_fetch_limit=5,
    )
    scheduler.run_once(now)
    scheduler.run_once(now + timedelta(minutes=5))
    assert provider.limits == [1, 5]
```

- [x] **Step 2: 运行测试并确认 RED**

Run:

```bash
cd collector
python -m pytest -q tests/test_config.py tests/test_scheduler.py
```

Expected: `catchup_fetch_limit` 不存在，或第二轮仍得到旧硬编码 50。

- [x] **Step 3: 实现最小配置与调度改动**

```python
@dataclass(frozen=True)
class CollectorSettings:
    catchup_fetch_limit: int = 5

catchup_fetch_limit=max(1, int(os.environ.get("CATCHUP_FETCH_LIMIT", "5")))
```

```python
class CollectorScheduler:
    def __init__(..., initial_fetch_limit: int = 1, catchup_fetch_limit: int = 5):
        self.catchup_fetch_limit = catchup_fetch_limit

limit = (
    self.initial_fetch_limit
    if checkpoint_before is None
    else self.catchup_fetch_limit
)
```

`collector_agent.main` 创建 Scheduler 时传入 `settings.catchup_fetch_limit`。

- [x] **Step 4: 运行目标测试并确认 GREEN**

Run:

```bash
cd collector
python -m pytest -q tests/test_config.py tests/test_scheduler.py
```

Expected: 0 failures。

---

### Task 2: Provider 最近 5 条边界与进程重启

**Files:**
- Modify: `collector/tests/test_x_provider.py`
- Modify: `collector/tests/test_scheduler.py`
- Modify: `collector/collector_agent/providers/x_opencli.py`

**Interfaces:**
- Consumes: provider `fetch(handle, checkpoint, limit)`
- Produces: 按旧到新排序且长度不超过 limit 的 `list[CollectedPost]`

- [x] **Step 1: 写超过上限和重启补抓失败测试**

X provider 测试让 runner 返回 checkpoint 后 12 条记录，调用 `fetch(..., limit=5)`，断言只返回最新 5 条且顺序为旧到新。

Scheduler 重启测试先把 checkpoint 写入 SQLite，关闭 Store 后重新打开，运行新 Scheduler 并断言 provider 收到原 checkpoint 和 limit 5，随后 checkpoint 推进到新批次最新 ID。

- [x] **Step 2: 运行测试并确认 RED**

Run:

```bash
cd collector
python -m pytest -q tests/test_x_provider.py tests/test_scheduler.py
```

Expected: X provider 返回超过 5 条，或 Scheduler 仍使用 50。

- [x] **Step 3: 实现 X provider 防御性截断**

```python
ordered = sorted(filtered, key=lambda post: int(post.external_id))
return ordered[-limit:]
```

Binance provider 已使用相同的 `ordered[-limit:]` 行为，不重复修改。

- [x] **Step 4: 运行 Collector 全量测试**

Run:

```bash
cd collector
python -m pytest -q
```

Expected: 0 failures。

---

### Task 3: 本机配置、launchd 与文档

**Files:**
- Modify: `collector/.env`
- Modify: `collector/.env.example`
- Modify: `docs/configuration.md`
- Modify: `docs/operations.md`
- Modify: `docs/verification.md`

**Interfaces:**
- Consumes: `CATCHUP_FETCH_LIMIT=5`
- Produces: 重启后的本机 Collector 与可复核运维说明

- [x] **Step 1: 写入配置和文档**

在 `collector/.env` 与 `.env.example` 增加：

```dotenv
CATCHUP_FETCH_LIMIT=5
```

文档明确首次 1 条、已有 checkpoint 最近最多 5 条、超过部分永久跳过、Outbox 保证上传失败不丢失。

- [x] **Step 2: 执行静态与全量验证**

Run:

```bash
python -m compileall -q collector/collector_agent
(cd collector && python -m pytest -q)
bash -n scripts/*.sh scripts/tests/*.sh
```

Expected: 所有命令 exit 0。

- [x] **Step 3: 重启 launchd Collector**

Run:

```bash
./scripts/collector-stop.sh
./scripts/collector-start.sh
./scripts/collector-status.sh
./scripts/collector-logs.sh --lines 50
```

Expected: status 为 running；新周期日志完整。

- [x] **Step 4: 验证远端 heartbeat**

要求：overall healthy、X authenticated、Binance Square healthy、Outbox 0；API/Web 不重建。
