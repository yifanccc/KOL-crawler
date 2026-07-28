# ntfy 标题格式调整 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将信号通知标题改为“平台 | KOL昵称 | 原帖北京时间”，正文继续只含中文摘要、标的和方向。

**Architecture:** 通知格式化函数从 Signal 关联的 RawPost 读取平台、`author_name` 和 `published_at`。平台做固定展示映射，时间用标准库 `zoneinfo` 转为 `Asia/Shanghai`；不读取 `author_handle` 作为标题名称。

**Tech Stack:** Python 3.12、SQLAlchemy、zoneinfo、pytest、Docker Compose。

## Global Constraints

- 不使用 subagent，不创建 worktree，不暂存或提交当前未跟踪基线。
- 标题固定为 `平台 | KOL名称 | 时间`。
- KOL 名称只使用 `RawPost.author_name`；缺失时显示 `未知 KOL`，不得回退到 `author_handle`。
- 时间使用 `RawPost.published_at` 转换到 `Asia/Shanghai`，格式为 `%Y-%m-%d %H:%M`；缺失时显示 `时间未知`。
- 正文严格保持摘要、标的、方向三行。

---

### Task 1: 修改通知标题格式

**Files:**
- Modify: `backend/tests/test_notifications.py`
- Modify: `backend/app/services/notifications.py`

**Interfaces:**
- Consumes: `Signal.raw_post_id`、`RawPost.platform`、`RawPost.author_name`、`RawPost.published_at`
- Produces: `_format_notification(session: Session, signal: Signal) -> tuple[str, str]`

- [x] **Step 1: 写失败测试**

在现有通知派发测试中把原帖昵称设为 `Serenity`，精确断言：

```python
assert title == "X | Serenity | 2026-07-09 08:00"
assert "aleabitoreddit" not in title
assert message == "摘要：AXTI 需求改善\n标的：AXTI\n方向：多"
```

再增加昵称缺失测试，原帖 `author_handle="account-name"`、`author_name=None` 时标题包含 `未知 KOL` 且不包含 `account-name`。

- [x] **Step 2: 运行测试确认红灯**

Run:

```bash
docker run --rm \
  -v "$PWD/backend/app:/app/app:ro" \
  -v "$PWD/backend/tests:/app/tests:ro" \
  -w /app kol-crawler-api \
  sh -lc 'pip install --no-cache-dir -q pytest pytest-mock respx && pytest -q tests/test_notifications.py'
```

Expected: 标题仍为 `AXTI 多 | AXTI 需求改善`，测试失败。

- [x] **Step 3: 实现最小标题格式**

在 `notifications.py` 中重新导入 `RawPost`，增加平台展示映射与北京时间格式化：

```python
from zoneinfo import ZoneInfo

PLATFORM_LABELS = {"x": "X", "binance_square": "Binance Square"}
SHANGHAI = ZoneInfo("Asia/Shanghai")

raw_post = session.get(RawPost, signal.raw_post_id)
platform = PLATFORM_LABELS.get(raw_post.platform, raw_post.platform) if raw_post else "未知平台"
kol_name = (raw_post.author_name if raw_post else None) or "未知 KOL"
published_at = raw_post.published_at if raw_post else None
if published_at is not None:
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    published_text = published_at.astimezone(SHANGHAI).strftime("%Y-%m-%d %H:%M")
else:
    published_text = "时间未知"
title = f"{platform} | {kol_name} | {published_text}"
```

正文构造保持不变。

- [x] **Step 4: 运行通知测试和后端完整测试**

Run: 同 Step 2，然后将最后的 pytest 命令改为 `pytest -q`。

Expected: 通知测试和后端完整测试全部通过。

### Task 2: 文档、部署与运行验收

**Files:**
- Modify: `docs/operations.md`
- Modify: `docs/verification.md`
- Modify: `docs/superpowers/specs/2026-07-13-ntfy-title-format-design.md`
- Modify: `docs/superpowers/plans/2026-07-13-ntfy-title-format.md`

**Interfaces:**
- Produces: 可复核的新标题格式说明和已部署 API。

- [x] **Step 1: 更新文档**

记录标题格式、昵称不回退到账号名称、北京时间规则以及正文三行不变；把设计状态改为“已实现”。

- [x] **Step 2: 重建 API**

Run:

```bash
docker compose build api
docker compose up -d --force-recreate --no-deps api
```

- [x] **Step 3: 运行健康检查**

Run:

```bash
curl -fsS http://localhost:8010/health
./scripts/collector-status.sh
```

Expected: API 返回 `status=ok`，Collector 仍由 launchd 运行。

- [x] **Step 4: 检查计划无未完成项**

将完成步骤勾选为 `[x]`，并运行：

```bash
rg -n "^- \[ \]" docs/superpowers/plans/2026-07-13-ntfy-title-format.md
```

Expected: 无输出。
