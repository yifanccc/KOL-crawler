# Exchange Trade Monitor Shared Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不依赖尚未确认的交易所私有字段的前提下，完成固定账号订阅、私有可见性、交易记录 ledger、确定性持仓推测、现有调度/outbox 接入、后端确定性 Signal 和管理端私有信号流。

**Architecture:** Exchange provider 只负责把已验证的来源响应映射为 `NormalizedTradeRecord`；共享 `TradeReconciler` 使用本机 SQLite 历史生成 `TradeEvent.positionAfter` 和推测持仓，并复用现有 outbox 上传。后端按平台绕过 LLM 生成现有 Signal，常规 API 强制过滤 private 订阅，`/api/admin/signals` 使用同一查询/序列化服务提供管理端私有信号。

**Tech Stack:** Python 3.12 Collector、SQLite、Playwright provider boundary、FastAPI、Pydantic 2、SQLAlchemy 2、MySQL/SQLite tests、Next.js 15、React 19、TypeScript、Node test runner、pytest。

## Global Constraints

- 平台类型固定为 `okx_orbit` 与 `binance_copy`；`binance_copy` 不得与 `binance_square` 混用。
- OKX 固定 Orbit User ID：`872838143249428480`；Binance 固定 Portfolio ID：`5075281354358777856`。
- 新平台必须使用 `platform_account_id` 定位，昵称只用于展示。
- 两个新平台服务端强制 `visibility=private`，默认 `intervalMinutes=10`。
- 现有调度语义保持“本轮开始时间加 10 分钟”，不改为高频 worker 或严格整点。
- 首次成功交易抓取只建立 baseline，不创建 outbox 消息，不发送历史通知。
- 空响应、登录失败和 schema 变化都不能推断为平仓，且不能推进 checkpoint。
- 交易方向、数量、价格、杠杆、动作和推测持仓不调用 LLM。
- 十进制数量和价格在 JSON 中使用字符串；不得用 `float` 做持仓运算。
- 常规 `/api/signals`、KOL、资产、详情和统计不返回 private 数据；私有数据只通过 `/api/admin/signals` 读取。
- 不保存密码、验证码、Cookie、Authorization、设备签名或完整来源响应 header。
- 本计划不创建 `okx_orbit` 或 `binance_copy` 真实 provider；必须先执行 `2026-08-09-exchange-private-trade-source-poc.md`，再依据真实夹具分别编写 provider 计划。
- 当前未跟踪文件 `1` 属于用户，所有暂存命令必须使用明确路径并排除它。

## File Responsibility Map

- `backend/app/models/subscription.py`: 订阅账号 ID、可见性和唯一约束。
- `backend/app/db/migrations.py`: 旧数据库的幂等列/约束升级。
- `backend/app/routers/admin.py`: 新平台订阅校验、私有 Signal 路由。
- `backend/app/routers/collector.py`: 向 Collector 下发 `accountId`。
- `backend/app/services/signal_feed.py`: 常规/私有 Signal 共用查询和序列化。
- `backend/app/services/trade_structurer.py`: 将规范化交易 payload 确定性转换为 Signal 字段。
- `collector/collector_agent/trade_models.py`: 交易记录、持仓和 batch 类型。
- `collector/collector_agent/trade_reconciler.py`: 纯函数持仓重算和 CollectedPost 构造。
- `collector/collector_agent/trade_store.py`: SQLite ledger、position estimate 和原子事务。
- `collector/collector_agent/models.py`: `ProviderTarget` 与帖子 batch 类型。
- `collector/tests/trade_samples.py`: Collector 交易测试共用的固定 target、checkpoint、record 和 batch factory。
- `collector/collector_agent/scheduler.py`: 两类 batch 的统一调度与健康状态边界。
- `frontend/src/lib/platforms.ts`: 平台标签和账号 ID 表单规则。
- `frontend/src/app/admin/signals/page.tsx`: 私有交易信号入口。

---

### Task 1: 订阅账号 ID、可见性与数据库迁移

**Files:**
- Modify: `backend/app/models/subscription.py:1-38`
- Modify: `backend/app/db/migrations.py:5-184`
- Modify: `backend/tests/test_migrations.py`

**Interfaces:**
- Produces: `TRADE_PLATFORMS = frozenset({"okx_orbit", "binance_copy"})`
- Produces: `Subscription.visibility: str`，值域 `public | private`
- Produces: 数据库唯一约束 `uq_subscriptions_platform_account`

- [ ] **Step 1: 写迁移失败测试**

在 `backend/tests/test_migrations.py` 增加：

```python
SUBSCRIPTION_TRADE_COLUMNS = {"platform_account_id", "visibility"}


def test_migrations_add_trade_identity_and_visibility_to_legacy_subscription() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata = MetaData()
    Table(
        "subscriptions",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("platform", String(32), nullable=False),
        Column("platform_handle", String(255), nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO subscriptions (id, platform, platform_handle) "
                "VALUES (1, 'x', 'legacy')"
            )
        )

    run_schema_migrations(engine)
    run_schema_migrations(engine)

    assert SUBSCRIPTION_TRADE_COLUMNS <= column_names(engine, "subscriptions")
    with engine.connect() as connection:
        visibility = connection.execute(
            text("SELECT visibility FROM subscriptions")
        ).scalars().all()
    assert visibility == ["public"]

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO subscriptions "
                "(id, platform, platform_handle, platform_account_id) "
                "VALUES (2, 'binance_copy', 'first', '5075281354358777856')"
            )
        )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO subscriptions "
                    "(id, platform, platform_handle, platform_account_id) "
                    "VALUES (3, 'binance_copy', 'duplicate', '5075281354358777856')"
                )
            )
```

该测试文件相应增加 `import pytest` 和 `from sqlalchemy.exc import IntegrityError`。

在 fresh-schema 测试中额外断言：

```python
constraints = inspect(engine).get_unique_constraints("subscriptions")
assert any(
    set(item["column_names"] or []) == {"platform", "platform_account_id"}
    for item in constraints
)
```

- [ ] **Step 2: 运行测试确认 RED**

Run:

```bash
cd backend && pytest -q tests/test_migrations.py -k 'trade_identity or fresh_schema'
```

Expected: FAIL，旧 schema 缺少 `platform_account_id`/`visibility`，fresh schema 缺少组合唯一约束。

- [ ] **Step 3: 实现模型与幂等迁移**

在 `backend/app/models/subscription.py` 定义：

```python
from sqlalchemy import UniqueConstraint

TRADE_PLATFORMS = frozenset({"okx_orbit", "binance_copy"})

__table_args__ = (
    CheckConstraint("interval_minutes >= 1", name="ck_subscription_interval_min"),
    UniqueConstraint(
        "platform",
        "platform_account_id",
        name="uq_subscriptions_platform_account",
    ),
)

visibility: Mapped[str] = mapped_column(
    String(16), nullable=False, default="public", server_default="public"
)
```

在 `MIGRATION_COLUMNS["subscriptions"]` 增加：

```python
"platform_account_id": "VARCHAR(255) NULL",
"visibility": "VARCHAR(16) NOT NULL DEFAULT 'public'",
```

MySQL 约束升级沿用现有检查方式：

```python
if engine.dialect.name == "mysql" and "subscriptions" in existing_tables:
    names = {
        item["name"]
        for item in inspect(connection).get_unique_constraints("subscriptions")
    }
    if "uq_subscriptions_platform_account" not in names:
        connection.execute(
            text(
                "ALTER TABLE subscriptions ADD CONSTRAINT "
                "uq_subscriptions_platform_account "
                "UNIQUE (platform, platform_account_id)"
            )
        )
```

SQLite legacy schema 不能通过 `ALTER TABLE ... ADD CONSTRAINT` 补约束，使用同名唯一索引，并在新增列后把任何预先存在的新交易平台订阅强制回填为 private：

```python
connection.execute(
    text(
        "UPDATE subscriptions SET visibility = 'private' "
        "WHERE platform IN ('okx_orbit', 'binance_copy')"
    )
)
if engine.dialect.name == "sqlite" and "subscriptions" in existing_tables:
    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_subscriptions_platform_account "
            "ON subscriptions (platform, platform_account_id)"
        )
    )
```

- [ ] **Step 4: 运行迁移测试与后端全量测试**

Run:

```bash
cd backend && pytest -q tests/test_migrations.py
cd backend && pytest -q
```

Expected: 迁移重复运行无错误；后端 0 failures。

- [ ] **Step 5: 提交数据库契约**

```bash
git add backend/app/models/subscription.py backend/app/db/migrations.py backend/tests/test_migrations.py
git diff --cached --check
git commit -m "feat: add private trade subscription identity"
```

---

### Task 2: Admin 与 Collector 订阅接口

**Files:**
- Modify: `backend/app/routers/admin.py:23-303`
- Modify: `backend/app/routers/collector.py:45-80`
- Modify: `backend/tests/test_admin.py`
- Modify: `backend/tests/test_collector_api.py`

**Interfaces:**
- Produces: `SubscriptionCreate.accountId: str | None`
- Produces: Admin payload 字段 `accountId`、`visibility`
- Produces: Collector config 字段 `accountId`
- Consumes: `TRADE_PLATFORMS`

- [ ] **Step 1: 写账号 ID 校验失败测试**

在 `backend/tests/test_admin.py` 增加：

```python
def test_private_trade_subscription_requires_fixed_account_id() -> None:
    reset_database()
    with TestClient(app) as client:
        headers = auth_headers(client)
        missing = client.post(
            "/api/admin/subscriptions",
            headers=headers,
            json={"platform": "binance_copy", "handle": "熬鹰资本"},
        )
        created = client.post(
            "/api/admin/subscriptions",
            headers=headers,
            json={
                "platform": "binance_copy",
                "handle": "熬鹰资本",
                "accountId": "5075281354358777856",
                "intervalMinutes": 10,
            },
        )
        duplicate = client.post(
            "/api/admin/subscriptions",
            headers=headers,
            json={
                "platform": "binance_copy",
                "handle": "仿冒昵称",
                "accountId": "5075281354358777856",
            },
        )
        mutable_interval = client.patch(
            f"/api/admin/subscriptions/{created.json()['item']['id']}",
            headers=headers,
            json={"intervalMinutes": 1},
        )
        mutable_account = client.patch(
            f"/api/admin/subscriptions/{created.json()['item']['id']}",
            headers=headers,
            json={"accountId": "11111111"},
        )

    assert missing.status_code == 422
    assert created.status_code == 200
    assert created.json()["item"]["accountId"] == "5075281354358777856"
    assert created.json()["item"]["visibility"] == "private"
    assert created.json()["item"]["intervalMinutes"] == 10
    assert duplicate.status_code == 409
    assert mutable_interval.status_code == 422
    assert mutable_account.status_code == 422
```

再增加一个 OKX 非数字 ID 返回 422 的断言，并确认旧 X 创建请求仍不要求 `accountId`。

- [ ] **Step 2: 写 Collector config 失败测试**

在 `backend/tests/test_collector_api.py` 的 insert fixture 中保留原 X 订阅，并增加：

```python
{
    "platform": "binance_copy",
    "platform_account_id": "5075281354358777856",
    "platform_handle": "熬鹰资本",
    "visibility": "private",
    "interval_minutes": 10,
    "enabled": True,
}
```

把原来的全字段断言和 `target` 选择改为：

```python
assert all(
    set(subscription)
    == {"id", "platform", "handle", "accountId", "intervalMinutes", "enabled"}
    for subscription in subscriptions
)
target = next(row for row in subscriptions if row["platform"] == "binance_copy")
assert target["accountId"] == "5075281354358777856"
regular = next(row for row in subscriptions if row["platform"] == "x")
assert regular["accountId"] is None
```

- [ ] **Step 3: 运行目标测试确认 RED**

Run:

```bash
cd backend && pytest -q tests/test_admin.py tests/test_collector_api.py -k 'account_id or collector_config'
```

Expected: FAIL，新平台不在允许集合、响应缺少 `accountId`/`visibility`。

- [ ] **Step 4: 实现增量 API 契约**

`SubscriptionCreate` 增加：

```python
from pydantic import model_validator

accountId: str | None = Field(default=None, pattern=r"^[0-9]{8,32}$")

@model_validator(mode="after")
def validate_trade_account_id(self) -> "SubscriptionCreate":
    if self.platform in TRADE_PLATFORMS and self.accountId is None:
        raise ValueError("accountId is required for private trade platforms")
    if self.platform in TRADE_PLATFORMS and self.intervalMinutes != 10:
        raise ValueError("private trade platforms require a 10 minute interval")
    if self.platform not in TRADE_PLATFORMS and self.accountId is not None:
        raise ValueError("accountId is only valid for private trade platforms")
    return self
```

创建逻辑使用账号 ID 查找新平台订阅：

```python
identity_filter = (
    Subscription.platform_account_id == payload.accountId
    if payload.platform in TRADE_PLATFORMS
    else Subscription.platform_handle == handle
)
existing = db.scalar(
    select(Subscription).where(
        Subscription.platform == payload.platform,
        identity_filter,
    )
)
```

新建和恢复路径都写入账号 ID、展示名和可见性；恢复软删除订阅时不能保留旧昵称：

```python
subscription.platform_account_id = payload.accountId
subscription.platform_handle = handle
subscription.visibility = "private" if payload.platform in TRADE_PLATFORMS else "public"
```

Admin `_subscription_payload` 增加两个只读字段：

```python
"accountId": subscription.platform_account_id,
"visibility": subscription.visibility,
```

Collector config 只增加定位所需的字段，不下发 visibility：

```python
"accountId": subscription.platform_account_id,
```

`PLATFORMS` 增加 `okx_orbit`、`binance_copy`。`SubscriptionUpdate` 设置 `model_config = ConfigDict(extra="forbid")` 且不定义 `accountId`，因此普通 PATCH 传入账号 ID 会返回 422；更新路由对交易平台拒绝任何非 10 的 `intervalMinutes`，避免创建后绕过固定周期。

- [ ] **Step 5: 运行目标测试和后端全量测试**

Run:

```bash
cd backend && pytest -q tests/test_admin.py tests/test_collector_api.py
cd backend && pytest -q
```

Expected: 0 failures；旧客户端字段保持不变且只多出可忽略字段。

- [ ] **Step 6: 提交 API 契约**

```bash
git add backend/app/routers/admin.py backend/app/routers/collector.py backend/tests/test_admin.py backend/tests/test_collector_api.py
git diff --cached --check
git commit -m "feat: expose fixed exchange account ids"
```

---

### Task 3: 交易领域模型与纯函数持仓重算

**Files:**
- Create: `collector/collector_agent/trade_models.py`
- Create: `collector/collector_agent/trade_reconciler.py`
- Modify: `collector/collector_agent/models.py:1-25`
- Create: `collector/tests/__init__.py`
- Create: `collector/tests/trade_samples.py`
- Create: `collector/tests/test_trade_reconciler.py`

**Interfaces:**
- Produces: `NormalizedTradeRecord`
- Produces: `TradeCheckpoint.encode()`、`TradeCheckpoint.decode()`
- Produces: `PositionEstimate`、`Reconciliation`
- Produces: `TradeEvent`
- Produces: `ProviderTarget`、`PostFetchResult`、`TradeRecordFetchResult`
- Produces: `reconcile_records(records, history_complete) -> Reconciliation`
- Produces: `build_collected_post(target, event) -> CollectedPost`

- [ ] **Step 1: 写动作与十进制运算失败测试**

```python
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from collector_agent.trade_models import NormalizedTradeRecord, TradeCheckpoint
from collector_agent.trade_reconciler import reconcile_records


def record(
    record_id,
    operation,
    side,
    quantity,
    *,
    revision="r1",
    observed_minute=0,
):
    return NormalizedTradeRecord(
        platform="binance_copy",
        account_id="5075281354358777856",
        source_record_id=record_id,
        revision=revision,
        operation=operation,
        symbol="BTCUSDT",
        position_side=side,
        quantity=Decimal(quantity) if quantity is not None else None,
        price=Decimal("50000"),
        leverage=Decimal("10"),
        event_time=datetime(2026, 8, 9, 1, int(record_id), tzinfo=UTC),
        observed_at=datetime(2026, 8, 9, 2, observed_minute, tzinfo=UTC),
        source_url=None,
        source_payload={"id": record_id},
    )


def test_reconcile_open_add_reduce_close_with_decimal_quantity() -> None:
    reconciliation = reconcile_records(
        [
            record("1", "OPEN", "LONG", "0.10"),
            record("2", "ADD", "LONG", "0.05"),
            record("3", "REDUCE", "LONG", "0.04"),
        ],
        history_complete=True,
    )
    assert reconciliation.positions["BTCUSDT"].quantity == Decimal("0.11")
    assert reconciliation.positions["BTCUSDT"].side == "LONG"
    assert reconciliation.positions["BTCUSDT"].status == "ACTIVE"
    assert reconciliation.events[1].position_after.quantity == Decimal("0.15")

    closed = reconcile_records(
        [record("1", "OPEN", "LONG", "0.10"), record("2", "CLOSE", "LONG", None)],
        history_complete=True,
    )
    assert closed.positions["BTCUSDT"].side == "FLAT"
    assert closed.positions["BTCUSDT"].quantity == Decimal("0")


def test_new_revision_emits_correction_but_replays_effective_operation() -> None:
    reconciliation = reconcile_records(
        [
            record("1", "OPEN", "LONG", "0.10"),
            record(
                "1",
                "OPEN",
                "LONG",
                "0.12",
                revision="r2",
                observed_minute=1,
            ),
        ],
        history_complete=True,
    )

    assert len(reconciliation.events) == 1
    assert reconciliation.events[0].action == "CORRECTION"
    assert reconciliation.events[0].record.operation == "OPEN"
    assert reconciliation.positions["BTCUSDT"].quantity == Decimal("0.12")


def test_trade_checkpoint_round_trips_versioned_json() -> None:
    checkpoint = TradeCheckpoint(
        event_time=datetime(2026, 8, 9, 1, 2, tzinfo=UTC),
        record_id="2",
    )
    assert TradeCheckpoint.decode(checkpoint.encode()) == checkpoint
    with pytest.raises(ValueError, match="checkpoint version"):
        TradeCheckpoint.decode('{"v":2,"eventTime":"2026-08-09T01:02:00Z","recordId":"2"}')
```

再增加：反手使用新方向、缺数量最多 MEDIUM、REDUCE 超过剩余量变 UNKNOWN、`history_complete=False` 不产生 HIGH、空记录不产生 FLAT。

- [ ] **Step 2: 运行测试确认 RED**

Run:

```bash
PYTHONPATH=collector pytest -q collector/tests/test_trade_reconciler.py
```

Expected: FAIL，模块不存在。

- [ ] **Step 3: 定义不可变领域类型**

在 `trade_models.py` 使用标准库 dataclass 和 `Decimal`，不增加依赖：

```python
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

TradeOperation = Literal["OPEN", "ADD", "REDUCE", "CLOSE", "REVERSE"]
TradeEventAction = Literal["OPEN", "ADD", "REDUCE", "CLOSE", "REVERSE", "CORRECTION"]
TradePositionSide = Literal["LONG", "SHORT", "UNKNOWN"]
EstimatedPositionSide = Literal["LONG", "SHORT", "FLAT", "UNKNOWN"]
PositionConfidence = Literal["HIGH", "MEDIUM", "LOW", "UNKNOWN"]
PositionStatus = Literal["ACTIVE", "FLAT", "UNKNOWN", "STALE"]

@dataclass(frozen=True)
class TradeCheckpoint:
    event_time: datetime
    record_id: str

    def encode(self) -> str:
        return json.dumps(
            {
                "v": 1,
                "eventTime": self.event_time.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                "recordId": self.record_id,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def decode(cls, value: str) -> "TradeCheckpoint":
        payload = json.loads(value)
        if payload.get("v") != 1:
            raise ValueError("unsupported trade checkpoint version")
        return cls(
            event_time=datetime.fromisoformat(payload["eventTime"].replace("Z", "+00:00")),
            record_id=str(payload["recordId"]),
        )

@dataclass(frozen=True)
class NormalizedTradeRecord:
    platform: str
    account_id: str
    source_record_id: str
    revision: str
    operation: TradeOperation
    symbol: str
    position_side: TradePositionSide
    quantity: Decimal | None
    price: Decimal | None
    leverage: Decimal | None
    event_time: datetime
    observed_at: datetime
    source_url: str | None
    source_payload: dict[str, Any]

@dataclass(frozen=True)
class PositionEstimate:
    symbol: str
    side: EstimatedPositionSide
    quantity: Decimal | None
    confidence: PositionConfidence
    status: PositionStatus
    as_of_event_time: datetime | None
    stale_since: datetime | None = None

@dataclass(frozen=True)
class TradeEvent:
    record: NormalizedTradeRecord
    action: TradeEventAction
    position_after: PositionEstimate

@dataclass(frozen=True)
class Reconciliation:
    events: list[TradeEvent]
    positions: dict[str, PositionEstimate]
```

在 `models.py` 增加：

先把现有 typing import 改为 `from typing import Any, Literal`，再增加：

```python
@dataclass(frozen=True)
class ProviderTarget:
    subscription_id: int
    platform: str
    account_id: str | None
    handle: str

@dataclass(frozen=True)
class PostFetchResult:
    posts: list[CollectedPost]
    candidate_checkpoint: str | None
    kind: Literal["posts"] = "posts"
```

在 `trade_models.py` 增加：

```python
@dataclass(frozen=True)
class TradeRecordFetchResult:
    records: list[NormalizedTradeRecord]
    candidate_checkpoint: str | None
    history_complete: bool
    kind: Literal["trade_records"] = "trade_records"
```

新增 `collector/tests/trade_samples.py`：

```python
from datetime import UTC, datetime
from decimal import Decimal

from collector_agent.models import ProviderTarget
from collector_agent.trade_models import (
    NormalizedTradeRecord,
    TradeCheckpoint,
    TradeOperation,
    TradePositionSide,
    TradeRecordFetchResult,
)

ACCOUNT_ID = "5075281354358777856"

def checkpoint(record_id: str) -> str:
    return TradeCheckpoint(
        event_time=datetime(2026, 8, 9, 1, int(record_id), tzinfo=UTC),
        record_id=record_id,
    ).encode()

def trade_target() -> ProviderTarget:
    return ProviderTarget(7, "binance_copy", ACCOUNT_ID, "熬鹰资本")

def sample_record(
    record_id: str,
    operation: TradeOperation,
    side: TradePositionSide,
    quantity: str | None,
) -> NormalizedTradeRecord:
    return NormalizedTradeRecord(
        platform="binance_copy",
        account_id=ACCOUNT_ID,
        source_record_id=record_id,
        revision="r1",
        operation=operation,
        symbol="BTCUSDT",
        position_side=side,
        quantity=Decimal(quantity) if quantity is not None else None,
        price=Decimal("50000"),
        leverage=Decimal("10"),
        event_time=datetime(2026, 8, 9, 1, int(record_id), tzinfo=UTC),
        observed_at=datetime(2026, 8, 9, 2, 0, tzinfo=UTC),
        source_url=None,
        source_payload={"id": record_id},
    )

def trade_result(
    records: list[NormalizedTradeRecord],
    record_id: str,
    *,
    history_complete: bool = True,
) -> TradeRecordFetchResult:
    return TradeRecordFetchResult(records, checkpoint(record_id), history_complete)
```

- [ ] **Step 4: 实现确定性重算规则**

`reconcile_records` 返回完整的 `Reconciliation`，必须：

```text
按 event_time、source_record_id、revision 稳定排序
同一 source_record_id 只使用 `(observed_at, revision)` 最大的 revision，保证时间相同时仍确定
events 按有效 revision 的时间顺序保存每条记录执行后的 position_after
positions 保存全部记录重算完成后的每个 symbol 最终状态
OPEN 设置方向和数量
ADD 仅对同方向相加
REDUCE 仅在数量可证实时相减
CLOSE 明确归零
REVERSE 用记录中的新方向和数量建立新仓位
同一 source_record_id 首次生效时 event.action = record.operation
同一 source_record_id 出现新 revision 时 event.action = CORRECTION，但重算使用新 revision 的 operation
CORRECTION 通过替换旧 revision 后全历史重算生效，不做增量叠加
任何矛盾转为 UNKNOWN
history_complete=False 时置信度最高为 LOW
```

领域测试读取 `reconciliation.positions["BTCUSDT"]` 做最终状态断言，并额外断言第二条 ADD 对应的 `reconciliation.events[1].position_after.quantity == Decimal("0.15")`，锁定“逐事件持仓”而不是给所有事件错误复用最终持仓。再用同一 `source_record_id`、不同 revision/observed_at 的两条记录断言只保留新 revision、`event.action == "CORRECTION"`，且数量运算使用新记录的 `operation`。

`build_collected_post` 使用 `{accountId}:{sourceRecordId}:{revision}` 作为 `external_id`，并把 Decimal 序列化为字符串。`raw_payload` 必须严格使用以下 camelCase 契约：

```python
def decimal_text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


{
    "schemaVersion": 1,
    "platform": record.platform,
    "accountId": record.account_id,
    "sourceRecordId": record.source_record_id,
    "revision": record.revision,
    "action": event.action,
    "effectiveAction": record.operation,
    "symbol": record.symbol,
    "positionSide": record.position_side,
    "quantity": decimal_text(record.quantity),
    "price": decimal_text(record.price),
    "leverage": decimal_text(record.leverage),
    "eventTime": record.event_time.isoformat(),
    "positionAfter": {
        "side": position.side,
        "quantity": decimal_text(position.quantity),
        "confidence": position.confidence,
        "status": position.status,
    },
    "sourceRecord": record.source_payload,
}
```

`sourceRecord` 在 provider 边界已按 POC 白名单脱敏；`content_hash` 对上述规范化 JSON 做 SHA-256。
`source_payload` 只允许 JSON-safe 的 dict/list/string/integer/boolean/null；不得把 `Decimal`、`datetime`、bytes 或第三方响应对象原样塞入。

- [ ] **Step 5: 运行领域测试**

Run:

```bash
PYTHONPATH=collector pytest -q collector/tests/test_trade_reconciler.py
```

Expected: 0 failures。

- [ ] **Step 6: 提交领域层**

```bash
git add collector/collector_agent/models.py collector/collector_agent/trade_models.py collector/collector_agent/trade_reconciler.py collector/tests/__init__.py collector/tests/trade_samples.py collector/tests/test_trade_reconciler.py
git diff --cached --check
git commit -m "feat: add deterministic trade position inference"
```

---

### Task 4: SQLite 交易 ledger 与原子 outbox

**Files:**
- Create: `collector/collector_agent/trade_store.py`
- Modify: `collector/collector_agent/db.py:1-60`
- Create: `collector/tests/test_trade_store.py`
- Modify: `collector/tests/test_outbox.py`

**Interfaces:**
- Produces: `CollectorStore.record_trade_fetch(subscription_id, target, result) -> int`
- Produces: `CollectorStore.mark_trade_positions_stale(subscription_id, stale_since) -> None`
- Produces: `CollectorStore.position_for(subscription_id, symbol) -> PositionEstimate | None`
- Consumes: `NormalizedTradeRecord`、`TradeEvent`、`build_collected_post`

- [ ] **Step 1: 写 baseline、去重和重启失败测试**

```python
from decimal import Decimal

from collector_agent.db import CollectorStore
from collector_agent.trade_models import TradeCheckpoint
from .trade_samples import sample_record, trade_result, trade_target


def test_first_trade_fetch_builds_baseline_without_outbox(tmp_path) -> None:
    store = CollectorStore(tmp_path / "collector.sqlite3")
    target = trade_target()
    result = trade_result([sample_record("1", "OPEN", "LONG", "0.10")], "1")

    inserted = store.record_trade_fetch(7, target, result)

    assert inserted == 0
    assert store.pending_posts() == []
    assert TradeCheckpoint.decode(store.checkpoint_for(7)).record_id == "1"
    assert store.position_for(7, "BTCUSDT").quantity == Decimal("0.10")


def test_second_trade_fetch_is_atomic_and_idempotent(tmp_path) -> None:
    path = tmp_path / "collector.sqlite3"
    store = CollectorStore(path)
    store.record_trade_fetch(
        7,
        trade_target(),
        trade_result([sample_record("1", "OPEN", "LONG", "0.10")], "1"),
    )
    update = trade_result(
        [
            sample_record("1", "OPEN", "LONG", "0.10"),
            sample_record("2", "ADD", "LONG", "0.05"),
        ],
        "2",
    )
    assert store.record_trade_fetch(7, trade_target(), update) == 1
    assert store.record_trade_fetch(7, trade_target(), update) == 0
    assert len(store.pending_posts()) == 1
    store.close()

    restarted = CollectorStore(path)
    assert TradeCheckpoint.decode(restarted.checkpoint_for(7)).record_id == "2"
    assert restarted.position_for(7, "BTCUSDT").quantity == Decimal("0.15")
```

增加一个测试，在 outbox 插入前故意抛错，断言 event、position、outbox 和 checkpoint 全部保持旧状态。

在 `test_outbox.py` 增加空帖子 batch 测试：`record_fetch(subscription_id, None, [])` 必须保留已有 checkpoint，不能把它清空。

再增加完整性失败测试：record 的 platform/account ID 与 `ProviderTarget` 不一致、candidate checkpoint 早于当前 checkpoint、或相同 `(source_record_id, revision)` 对应不同规范化语义时，都抛错并保持 ledger、position、outbox、checkpoint 原状。

- [ ] **Step 2: 运行测试确认 RED**

Run:

```bash
PYTHONPATH=collector pytest -q collector/tests/test_trade_store.py
```

Expected: FAIL，交易 store API 不存在。

- [ ] **Step 3: 建立 ledger schema**

在同一个 SQLite connection 上创建：

```sql
CREATE TABLE IF NOT EXISTS trade_events (
  id INTEGER PRIMARY KEY,
  subscription_id INTEGER NOT NULL,
  source_record_id TEXT NOT NULL,
  revision TEXT NOT NULL,
  event_time TEXT NOT NULL,
  first_observed_at TEXT NOT NULL,
  last_observed_at TEXT NOT NULL,
  normalized_json TEXT NOT NULL,
  UNIQUE(subscription_id, source_record_id, revision)
);
CREATE TABLE IF NOT EXISTS position_estimates (
  subscription_id INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  quantity TEXT,
  confidence TEXT NOT NULL,
  status TEXT NOT NULL,
  as_of_event_time TEXT,
  stale_since TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(subscription_id, symbol)
);
```

- [ ] **Step 4: 实现单事务写入**

`record_trade_fetch` 在一个 `with self.connection:` 中完成：

```text
判断 baseline = checkpoint_before is None
先验证全部 record 与 target 相符，并用 TradeCheckpoint 拒绝 checkpoint 倒退
INSERT OR IGNORE 新 revision；重复 revision 的 canonical normalized_json 相同才更新 last_observed_at
读取该订阅全部规范化记录
调用 reconcile_records，upsert reconciliation.positions
非 baseline 时，只为本轮新插入且在 reconciliation.events 中生效的 revision 创建 CollectedPost/outbox
使用对应 TradeEvent 自己的 position_after，不能复用该 symbol 的最终 position
最后写 next_checkpoint = candidate_checkpoint if candidate_checkpoint is not None else checkpoint_before
```

`canonical normalized_json` 不含 `observed_at`，该时间只写 `first_observed_at/last_observed_at`；其余语义字段必须一致，否则视为 revision collision。`record_fetch` 同样只在 `candidate_checkpoint is not None` 时更新 checkpoint。`mark_trade_positions_stale` 只更新 `status='STALE'` 和 `stale_since`，不改变 side、quantity、confidence 或 checkpoint。

- [ ] **Step 5: 运行 ledger 与原 outbox 测试**

Run:

```bash
PYTHONPATH=collector pytest -q collector/tests/test_trade_store.py collector/tests/test_outbox.py
```

Expected: 0 failures；原帖子 outbox 行为不变。

- [ ] **Step 6: 提交 ledger**

```bash
git add collector/collector_agent/trade_store.py collector/collector_agent/db.py collector/tests/test_trade_store.py collector/tests/test_outbox.py
git diff --cached --check
git commit -m "feat: persist trade ledger atomically"
```

---

### Task 5: 现有 Provider 与 Scheduler 接入 batch 合约

**Files:**
- Modify: `collector/collector_agent/providers/x_opencli.py`
- Modify: `collector/collector_agent/providers/binance_square.py`
- Modify: `collector/collector_agent/scheduler.py:1-126`
- Modify: `collector/tests/test_x_provider.py`
- Modify: `collector/tests/test_binance_provider.py`
- Modify: `collector/tests/test_scheduler.py`

**Interfaces:**
- Consumes: `ProviderTarget`
- Consumes: `PostFetchResult`
- Consumes: `TradeRecordFetchResult`
- Consumes: Collector config `accountId`
- Consumes: `CollectorStore.record_fetch`、`record_trade_fetch`、`mark_trade_positions_stale`

- [ ] **Step 1: 写目标 ID 和两类 batch 失败测试**

在 `collector/tests/test_scheduler.py` 增加 fake trade provider：

```python
from collector_agent.providers.base import ProviderHealth
from collector_agent.trade_models import TradeRecordFetchResult
from .trade_samples import checkpoint, sample_record


class TradeProvider:
    def __init__(self):
        self.targets = []
        self._health = ProviderHealth("authenticated")

    def fetch(self, target, current_checkpoint, limit):
        self.targets.append(target)
        return TradeRecordFetchResult(
            records=[sample_record("1", "OPEN", "LONG", "0.10")],
            candidate_checkpoint=checkpoint("1"),
            history_complete=True,
        )

    def health(self):
        return self._health
```

断言：

```python
assert provider.targets[0].account_id == "5075281354358777856"
assert provider.targets[0].handle == "熬鹰资本"
assert store.pending_posts() == []  # first fetch is baseline
assert scheduler.next_check[21] == now + timedelta(minutes=10)
```

增加两类失败测试：第二轮 `login_required` 后 checkpoint 不变且 position 状态为 STALE；provider 直接抛异常时也必须标记 STALE，且保留同一 checkpoint/quantity。

- [ ] **Step 2: 运行 Scheduler 测试确认 RED**

Run:

```bash
PYTHONPATH=collector pytest -q collector/tests/test_scheduler.py -k 'trade or account_id'
```

Expected: FAIL，Scheduler 仍只传 handle 并假定返回 list。

- [ ] **Step 3: 让现有 provider 返回 PostFetchResult**

X 和 Binance Square provider 接收 `ProviderTarget`，分别只使用 `target.handle`。候选 checkpoint 由 provider 按当前排序产生；没有新帖子时保留传入 checkpoint。

更新原 provider 测试，断言 `result.posts` 和 `result.candidate_checkpoint`，保证解析结果与改造前一致。

- [ ] **Step 4: 实现 Scheduler 判别分支**

核心流程固定为：

```python
target = ProviderTarget(
    subscription_id=subscription_id,
    platform=subscription["platform"],
    account_id=subscription.get("accountId"),
    handle=subscription["handle"],
)
result = provider.fetch(target, checkpoint_before, limit)
health = provider.health() if hasattr(provider, "health") else None
if health is not None and health.status not in {"healthy", "authenticated"}:
    if subscription["platform"] in {"okx_orbit", "binance_copy"}:
        self.store.mark_trade_positions_stale(subscription_id, now)
    continue
if result.kind == "posts":
    inserted = self.store.record_fetch(
        subscription_id, result.candidate_checkpoint, result.posts
    )
else:
    inserted = self.store.record_trade_fetch(subscription_id, target, result)
```

异常分支对交易平台同样调用 `mark_trade_positions_stale(subscription_id, now)`，然后沿用现有 provider failure 与告警逻辑。不要用空 `records` 或空 `posts` 覆盖 checkpoint；只使用 provider 明确返回的 `candidate_checkpoint`。

成功日志按 result 类型记录实际抓取数量；交易平台且 `checkpoint_before is None` 时状态固定为 `baseline_created`，否则为 `success`。baseline 日志与返回的 outbox 数量都必须是 0。

- [ ] **Step 5: 运行 Collector 全量测试**

Run:

```bash
PYTHONPATH=collector pytest -q collector/tests
```

Expected: 0 failures；现有 X/Binance Square provider 与调度测试不回归。

- [ ] **Step 6: 提交调度契约**

```bash
git add collector/collector_agent/providers/x_opencli.py collector/collector_agent/providers/binance_square.py collector/collector_agent/scheduler.py collector/tests/test_x_provider.py collector/tests/test_binance_provider.py collector/tests/test_scheduler.py
git diff --cached --check
git commit -m "refactor: add typed collector fetch batches"
```

---

### Task 6: 后端确定性交易 structurer

**Files:**
- Create: `backend/app/services/trade_structurer.py`
- Modify: `backend/app/services/analysis_queue.py:14-76`
- Create: `backend/tests/test_trade_structurer.py`
- Modify: `backend/tests/test_collector_ingestion.py`
- Modify: `backend/app/services/notifications.py:13-99`
- Modify: `backend/tests/test_notifications.py`

**Interfaces:**
- Produces: `TradePayload.model_validate_json(raw_post.raw_json)`
- Produces: `build_trade_signal_fields(raw_post, subscription) -> TradeSignalFields`
- Produces: `structured_status="deterministic"`
- Consumes: Collector `rawPayload.schemaVersion == 1`

- [ ] **Step 1: 写不调用 LLM 的失败测试**

```python
import json
from unittest.mock import Mock

from sqlalchemy import select

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import RawPost, Signal, Subscription
from app.services.analysis_queue import process_pending_posts


def make_trade_raw_post(
    *,
    action: str,
    side: str,
    quantity: str | None,
    position_after: dict,
    effective_action: str | None = None,
) -> RawPost:
    payload = {
        "schemaVersion": 1,
        "platform": "binance_copy",
        "accountId": "5075281354358777856",
        "sourceRecordId": "record-2",
        "revision": "r1",
        "action": action,
        "effectiveAction": effective_action or action,
        "symbol": "BTCUSDT",
        "positionSide": side,
        "quantity": quantity,
        "price": "50000",
        "leverage": "10",
        "eventTime": "2026-08-09T02:00:00Z",
        "positionAfter": position_after,
        "sourceRecord": {"id": "record-2"},
    }
    return RawPost(
        platform="binance_copy",
        external_id="5075281354358777856:record-2:r1",
        author_handle="熬鹰资本",
        author_name="熬鹰资本",
        raw_text="熬鹰资本 BTCUSDT 减仓",
        raw_json=json.dumps(payload, ensure_ascii=False),
        analysis_status="pending",
    )


def test_trade_post_is_structured_deterministically_without_model_call() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    raw_post = make_trade_raw_post(
        action="REDUCE",
        side="LONG",
        quantity="0.04",
        position_after={
            "side": "LONG",
            "quantity": "0.11",
            "confidence": "HIGH",
            "status": "ACTIVE",
        },
    )
    structurer = Mock()
    structurer.structure.side_effect = AssertionError("LLM must not run")

    with SessionLocal() as session:
        subscription = Subscription(
            platform="binance_copy",
            platform_account_id="5075281354358777856",
            platform_handle="熬鹰资本",
            visibility="private",
            interval_minutes=10,
        )
        session.add(subscription)
        session.flush()
        raw_post.subscription_id = subscription.id
        session.add(raw_post)
        session.commit()
        assert process_pending_posts(session, structurer) == 1
        signal = session.scalar(select(Signal))

    structurer.structure.assert_not_called()
    assert signal.actionable is True
    assert signal.stance == "neutral"
    assert signal.structured_status == "deterministic"
    assert signal.confidence == "高"
    assert "推测持仓" in signal.summary_cn
```

增加无效 `schemaVersion`、非法 Decimal、缺 `sourceRecordId` 的测试，断言 RawPost 进入 failed 且不调用模型。再覆盖 payload account ID 与订阅不一致、payload platform 与 RawPost 不一致、external ID 不等于 `{accountId}:{sourceRecordId}:{revision}`、缺订阅或订阅不是 private 的情况；这些完整性错误都必须 failed，不能创建 Signal。

- [ ] **Step 2: 运行目标测试确认 RED**

Run:

```bash
cd backend && pytest -q tests/test_trade_structurer.py tests/test_collector_ingestion.py -k trade
```

Expected: FAIL，交易平台仍走普通 structurer。

- [ ] **Step 3: 定义严格 payload schema**

`TradePayload` 使用 alias 接收 camelCase：

```python
class PositionAfter(BaseModel):
    side: Literal["LONG", "SHORT", "FLAT", "UNKNOWN"]
    quantity: Decimal | None
    confidence: Literal["HIGH", "MEDIUM", "LOW", "UNKNOWN"]
    status: Literal["ACTIVE", "FLAT", "UNKNOWN", "STALE"]

class TradePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    schema_version: Literal[1] = Field(alias="schemaVersion")
    platform: Literal["okx_orbit", "binance_copy"]
    account_id: str = Field(alias="accountId", pattern=r"^[0-9]{8,32}$")
    source_record_id: str = Field(alias="sourceRecordId", min_length=1)
    revision: str = Field(min_length=1)
    action: Literal["OPEN", "ADD", "REDUCE", "CLOSE", "REVERSE", "CORRECTION"]
    effective_action: Literal["OPEN", "ADD", "REDUCE", "CLOSE", "REVERSE"] = Field(
        alias="effectiveAction"
    )
    symbol: str
    position_side: Literal["LONG", "SHORT", "UNKNOWN"] = Field(alias="positionSide")
    quantity: Decimal | None
    price: Decimal | None
    leverage: Decimal | None
    event_time: datetime = Field(alias="eventTime")
    position_after: PositionAfter = Field(alias="positionAfter")
    source_record: dict[str, Any] = Field(default_factory=dict, alias="sourceRecord")
```

`PositionAfter` 同样设置 `extra="forbid"`。为 `quantity`、`price`、`leverage` 和 `positionAfter.quantity` 增加 `mode="before"` validator，只接受字符串或 `None`；收到 JSON number 时拒绝，避免二进制浮点进入持仓事实。`sourceRecord` 不参与 Signal 数值计算。

```python
def decimal_string(value: Any) -> Any:
    if value is None or isinstance(value, str):
        return value
    raise ValueError("decimal fields must be JSON strings")

@field_validator("quantity", "price", "leverage", mode="before")
@classmethod
def validate_decimal_strings(cls, value: Any) -> Any:
    return decimal_string(value)
```

`PositionAfter.quantity` 使用同一个 validator。

`build_trade_signal_fields` 在字段映射前还必须校验：subscription 存在且 `visibility == "private"`，`raw_post.platform == payload.platform == subscription.platform`，`payload.account_id == subscription.platform_account_id`，以及 `raw_post.external_id == f"{account_id}:{source_record_id}:{revision}"`。任何不一致都抛 `ValueError`，由现有 analysis queue 失败路径记录，不进入 LLM fallback。

- [ ] **Step 4: 实现字段映射**

映射固定为：

```text
OPEN/ADD/REVERSE + LONG -> bullish / 多
OPEN/ADD/REVERSE + SHORT -> bearish / 空
REDUCE/CLOSE/CORRECTION -> neutral / 中性
所有六种动作 -> actionable=True
HIGH/MEDIUM/LOW/UNKNOWN -> 90/60/30/0
OPEN/REVERSE/CLOSE importance=4
ADD/REDUCE importance=3
CORRECTION importance=2
```

普通事件必须校验 `action == effectiveAction`；只有 `action == "CORRECTION"` 时二者可以不同。方向映射读取普通事件的 `action`，修订事件固定为 neutral；所有数值始终读取 payload 字段，不从摘要反解。

摘要格式：

```text
{KOL} {symbol} {动作中文}，方向 {多/空/未知}，本次数量 {quantity 或 未知}；推测持仓 {positionAfter.side} {positionAfter.quantity 或 未知}（置信度 {高/中/低/未知}）
```

风险提示固定包含“持仓由交易记录推测，可能因记录缺失或延迟与实际不同”。

`build_trade_signal_fields` 返回下列薄包装，继续复用现有 `StructuredSignal`，同时保留“减仓/平仓也是 actionable”这一交易事件语义：

```python
@dataclass(frozen=True)
class TradeSignalFields:
    structured: StructuredSignal
    actionable: bool = True
    structured_status: Literal["deterministic"] = "deterministic"
    tag_source: Literal["deterministic"] = "deterministic"
```

- [ ] **Step 5: 在 analysis queue 按平台分流**

`process_pending_posts` 对 `okx_orbit`、`binance_copy` 调用 deterministic builder，并从 `TradeSignalFields` 读取显式 `actionable=True`、`structured_status` 和 `tag_source`；其他平台保持现有 structurer，并继续用 stance 推导 actionable、`ok/fallback` 状态和 `llm` tag source。Signal/Asset/Tag/notification 持久化继续走同一段共用代码。不要让 `REDUCE/CLOSE -> neutral` 被现有 `stance in {bullish, bearish}` 逻辑错误改成不可操作。

通知平台标签增加：

```python
PLATFORM_LABELS = {
    "x": "X",
    "binance_square": "Binance Square",
    "okx_orbit": "OKX Orbit",
    "binance_copy": "Binance Copy",
}
```

- [ ] **Step 6: 运行目标测试与后端全量测试**

Run:

```bash
cd backend && pytest -q tests/test_trade_structurer.py tests/test_collector_ingestion.py tests/test_notifications.py
cd backend && pytest -q
```

Expected: 0 failures。

- [ ] **Step 7: 提交确定性分析**

```bash
git add backend/app/services/trade_structurer.py backend/app/services/analysis_queue.py backend/app/services/notifications.py backend/tests/test_trade_structurer.py backend/tests/test_collector_ingestion.py backend/tests/test_notifications.py
git diff --cached --check
git commit -m "feat: structure trade events without llm"
```

---

### Task 7: 常规与私有 Signal 查询隔离

**Files:**
- Create: `backend/app/services/signal_feed.py`
- Modify: `backend/app/routers/public.py:90-319`
- Modify: `backend/app/routers/admin.py`
- Modify: `backend/tests/test_public_api.py`
- Modify: `backend/tests/test_admin.py`

**Interfaces:**
- Produces: `signal_page(db, filters, visibility) -> dict`
- Produces: `GET /api/admin/signals`
- Consumes: `Subscription.visibility`

- [ ] **Step 1: 写 private 数据隔离失败测试**

在 `backend/tests/test_admin.py` 现有 imports 中加入 `KolProfile`，并把下列 helper 和主断言放在该文件；它可以直接复用现有 `reset_database`、`auth_headers`、`SessionLocal`、`TestClient` 和 `app`：

```python
def seed_signal(*, visibility: str, platform: str, summary: str) -> int:
    with SessionLocal.begin() as session:
        kol = KolProfile(platform=platform, display_name=f"{platform}-kol")
        session.add(kol)
        session.flush()
        subscription = Subscription(
            kol_profile_id=kol.id,
            platform=platform,
            platform_handle=kol.display_name,
            visibility=visibility,
            interval_minutes=10,
        )
        session.add(subscription)
        session.flush()
        raw_post = RawPost(
            subscription_id=subscription.id,
            platform=platform,
            external_id=f"{platform}-{summary}",
            raw_text=summary,
            analysis_status="completed",
        )
        session.add(raw_post)
        session.flush()
        signal = Signal(
            raw_post_id=raw_post.id,
            subscription_id=subscription.id,
            actionable=True,
            stance="neutral",
            summary=summary,
            structured_status="deterministic",
        )
        session.add(signal)
        session.flush()
        return signal.id


def test_private_trade_signal_only_appears_in_admin_feed() -> None:
    reset_database()
    seed_signal(visibility="public", platform="x", summary="公开信号")
    private_signal_id = seed_signal(
        visibility="private", platform="binance_copy", summary="私有交易变化"
    )

    with TestClient(app) as client:
        headers = auth_headers(client)
        regular = client.get("/api/signals", headers=headers)
        private = client.get("/api/admin/signals", headers=headers)
        leaked_detail = client.get(f"/api/signals/{private_signal_id}", headers=headers)

    with TestClient(app) as anonymous_client:
        anonymous = anonymous_client.get("/api/admin/signals")

    assert [item["summary"] for item in regular.json()["items"]] == ["公开信号"]
    assert [item["summary"] for item in private.json()["items"]] == ["私有交易变化"]
    assert leaked_detail.json()["item"] is None
    assert anonymous.status_code == 401
```

增加 KOL、Asset 和 `overallTotal` 测试：private-only KOL/Asset 不出现在常规接口，public+private 共用 Asset 时仍显示一次。再构造一条 `Signal.subscription_id=None`、但 `RawPost.subscription_id` 指向 private 订阅的数据，断言它仍不能从常规列表和详情泄漏。

- [ ] **Step 2: 运行隔离测试确认 RED**

Run:

```bash
cd backend && pytest -q tests/test_public_api.py tests/test_admin.py -k private
```

Expected: FAIL，常规查询没有 visibility 过滤且 admin signals 路由不存在。

- [ ] **Step 3: 提取共用 Signal 查询服务**

把 `public.py` 中 Signal 过滤、计数和 payload 序列化移动到 `signal_feed.py`，保持响应字段和排序不变。服务入口：

```python
def signal_page(
    db: Session,
    *,
    visibility: Literal["public", "private"],
    kol_id: int | None,
    platform: str | None,
    asset: str | None,
    tag: str | None,
    stance: str | None,
    actionable: bool | None,
    time_range: str,
    min_importance: int,
    limit: int,
    offset: int,
) -> dict:
    ...
```

visibility 条件使用 `effective_subscription_id = coalesce(Signal.subscription_id, RawPost.subscription_id)` 关联 `Subscription.id`，防止 Signal 外键意外为空但 RawPost 已关联 private 订阅时泄漏。常规查询只在两个 subscription ID 都为空时把历史信号视为 public；private 查询只允许 effective subscription 明确关联 `visibility='private'` 的信号。

实现时将 scope 固定为：public 使用 outer join，并允许 `Subscription.visibility == "public" OR (Signal.subscription_id IS NULL AND RawPost.subscription_id IS NULL)`；private 使用 Subscription join 且只允许 `visibility == "private"`。`overallTotal` 也必须从同一个 scope base query 计数，不能继续直接 `COUNT(signals.id)`。

- [ ] **Step 4: 接入常规与 Admin 路由**

- `/api/signals` 调用 `visibility="public"`。
- `/api/admin/signals` 复制现有查询参数定义并调用 `visibility="private"`。
- `/api/signals/{id}` 在返回前执行同一 public scope 检查。
- `/api/kols` 只 join public subscriptions。
- `/api/assets` 排除仅被 private Signal 引用的 Asset；无任何 Signal 的旧 Asset 保持现有可见性。
- 常规 `overallTotal`、`actionableTotal` 和 `total` 都基于 public scope。

- [ ] **Step 5: 运行 API 测试**

Run:

```bash
cd backend && pytest -q tests/test_public_api.py tests/test_admin.py
cd backend && pytest -q
```

Expected: 0 failures；现有分页、过滤和计数断言保持通过。

- [ ] **Step 6: 提交查询隔离**

```bash
git add backend/app/services/signal_feed.py backend/app/routers/public.py backend/app/routers/admin.py backend/tests/test_public_api.py backend/tests/test_admin.py
git diff --cached --check
git commit -m "feat: isolate private trade signals"
```

---

### Task 8: 管理端固定账号订阅表单

**Files:**
- Create: `frontend/src/lib/platforms.ts`
- Create: `frontend/tests/platforms.test.mjs`
- Modify: `frontend/src/lib/types.ts:76-107`
- Modify: `frontend/src/lib/api.ts:280-369`
- Modify: `frontend/src/components/AdminShell.tsx:27-310`
- Modify: `frontend/src/app/globals.css`

**Interfaces:**
- Produces: `platformLabel(platform) -> string`
- Produces: `requiresAccountId(platform) -> boolean`
- Produces: `AdminSubscription.accountId`、`visibility`
- Consumes: Admin API 增量字段

- [ ] **Step 1: 写平台规则失败测试**

```javascript
import assert from "node:assert/strict";
import test from "node:test";

const platforms = await import("../src/lib/platforms.ts");

test("private trade platforms require immutable account ids", () => {
  assert.equal(platforms.requiresAccountId("okx_orbit"), true);
  assert.equal(platforms.requiresAccountId("binance_copy"), true);
  assert.equal(platforms.requiresAccountId("binance_square"), false);
});

test("platform labels are explicit", () => {
  assert.equal(platforms.platformLabel("okx_orbit"), "OKX Orbit");
  assert.equal(platforms.platformLabel("binance_copy"), "Binance Copy");
  assert.equal(platforms.platformLabel("binance_square"), "Binance 广场");
});
```

- [ ] **Step 2: 运行测试确认 RED**

Run:

```bash
cd frontend && node --experimental-strip-types --test tests/platforms.test.mjs
```

Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现类型、解析和平台规则**

`AdminSubscription` 增加：

```typescript
accountId?: string | null;
visibility: "public" | "private";
```

`AdminSubscriptionInput` 增加 `accountId?: string`。`normalizeAdminSubscription` 对缺失旧字段使用 `null` 和 `public`，保证向后兼容。`updateAdminSubscription` 的 payload 类型明确写为 `Omit<AdminSubscriptionInput, "platform" | "handle" | "accountId">`，让不可变账号 ID 同时受前端类型和后端 422 约束。

`platforms.ts` 使用固定映射，不用二元 `x ? X : Binance` fallback。

- [ ] **Step 4: 修改 Admin 表单**

`SubscriptionForm`、`newForm` 和 `subscriptionForm` 增加 `accountId`；编辑时从只读响应回填，创建新订阅时为空。仅 `requiresAccountId(form.platform)` 时渲染必填输入：

```tsx
<label>
  <span>{form.platform === "okx_orbit" ? "Orbit User ID" : "Portfolio ID"}</span>
  <input
    disabled={Boolean(selectedId)}
    inputMode="numeric"
    pattern="[0-9]{8,32}"
    required
    value={form.accountId}
    onChange={(event) => setForm({ ...form, accountId: event.target.value })}
  />
</label>
```

平台 select 的 `onChange` 在切换到交易平台时同时写入 `intervalMinutes: "10"`；交易平台的间隔输入设置 `disabled`，其他平台保持现有可编辑行为。创建请求仅在 `requiresAccountId` 时发送 `accountId`；更新请求不发送。订阅列表和删除确认统一使用 `platformLabel`，并显示固定 ID、10 分钟和 `私有` badge。交易平台的 prompt editor 保留但标注“交易数值不使用模型”，避免用户误以为 prompt 会改变交易解析。

- [ ] **Step 5: 运行前端测试和类型检查**

Run:

```bash
cd frontend && node --experimental-strip-types --test tests/*.test.mjs
cd frontend && npx tsc --noEmit
```

Expected: 0 failures，TypeScript 0 errors。

- [ ] **Step 6: 提交订阅 UI**

```bash
git add frontend/src/lib/platforms.ts frontend/tests/platforms.test.mjs frontend/src/lib/types.ts frontend/src/lib/api.ts frontend/src/components/AdminShell.tsx frontend/src/app/globals.css
git diff --cached --check
git commit -m "feat: manage fixed exchange account subscriptions"
```

---

### Task 9: 管理端私有交易信号页面

**Files:**
- Create: `frontend/src/app/admin/signals/page.tsx`
- Create: `frontend/src/components/PrivateSignalFeed.tsx`
- Create: `frontend/tests/privateSignals.test.mjs`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/components/AdminShell.tsx`
- Modify: `frontend/src/app/globals.css`

**Interfaces:**
- Produces: `fetchPrivateSignalPage(query) -> Promise<SignalPage>`
- Produces: `normalizeSignalPage(json, query) -> SignalPage`
- Produces: `/admin/signals`
- Consumes: `GET /api/admin/signals`
- Reuses: `FeedCard`、`FilterBar`、`signalFeed.ts` pagination helpers

- [ ] **Step 1: 写私有 endpoint 选择失败测试**

在 `frontend/src/lib/api.ts` 导出纯函数：

```typescript
export function signalEndpoint(scope: "regular" | "private") {
  return scope === "private" ? "/api/admin/signals" : "/api/signals";
}
```

测试：

```javascript
test("private signal requests use the admin endpoint", () => {
  assert.equal(api.signalEndpoint("private"), "/api/admin/signals");
  assert.equal(api.signalEndpoint("regular"), "/api/signals");
});
```

- [ ] **Step 2: 运行测试确认 RED**

Run:

```bash
cd frontend && node --experimental-strip-types --test tests/privateSignals.test.mjs
```

Expected: FAIL，`signalEndpoint` 不存在。

- [ ] **Step 3: 实现私有 Signal API client**

先把当前 `fetchSignalPage` 第 240-252 行的响应解析提取为纯函数，并让常规、私有两个 client 共用：

```typescript
export function normalizeSignalPage(
  json: unknown,
  params: SignalQuery = {},
): SignalPage {
  const items = normalizeItems(json).map(normalizeSignal);
  const source = isRecord(json) ? json : {};
  const total = numberValue(source.total) ?? items.length;
  return {
    items,
    total,
    overallTotal: numberValue(source.overallTotal) ?? total,
    actionableTotal:
      numberValue(source.actionableTotal) ??
      items.filter((signal) => signal.actionable).length,
    limit: numberValue(source.limit) ?? params.limit ?? 100,
    offset: numberValue(source.offset) ?? params.offset ?? 0,
  };
}

export async function fetchPrivateSignalPage(query: SignalQuery = {}): Promise<SignalPage> {
  const suffix = buildSignalQuery(query);
  const json = await getJson(`${signalEndpoint("private")}${suffix ? `?${suffix}` : ""}`);
  return normalizeSignalPage(json, query);
}
```

`fetchSignalPage` 同样改为调用 `signalEndpoint("regular")` 和 `normalizeSignalPage(json, params)`，响应行为不得变化。

- [ ] **Step 4: 实现 PrivateSignalFeed**

组件必须复用：

```text
FeedCard
FilterBar
defaultDashboardFilters
appendSignalPage / refreshSignalPage / hasMoreSignals / SIGNAL_BATCH_SIZE
```

页面标题为“私有交易信号”，说明文字固定为“交易事件来自登录态只读记录；持仓为推测值，不代表交易所实时持仓”。只显示 private endpoint 返回的数据，不从常规 `fetchKols`/`fetchAssets` 混入私有筛选项；筛选建议从当前私有 Signal 页聚合。

- [ ] **Step 5: 添加管理端入口**

在 Admin header 增加链接：

```tsx
<Link href="/admin/signals">私有交易信号</Link>
```

`/admin/signals/page.tsx` 只渲染 `PrivateSignalFeed`；现有 middleware 已保护该路径，不新增认证方案。

- [ ] **Step 6: 运行前端测试、类型检查和 build**

Run:

```bash
cd frontend && node --experimental-strip-types --test tests/*.test.mjs
cd frontend && npx tsc --noEmit
cd frontend && npm run build
```

Expected: tests 0 failures；TypeScript 0 errors；Next production build 成功。

- [ ] **Step 7: 提交私有信号页**

```bash
git add frontend/src/app/admin/signals/page.tsx frontend/src/components/PrivateSignalFeed.tsx frontend/tests/privateSignals.test.mjs frontend/src/lib/api.ts frontend/src/components/AdminShell.tsx frontend/src/app/globals.css
git diff --cached --check
git commit -m "feat: add private trade signal feed"
```

---

### Task 10: 合成 Trade provider 端到端回归

**Files:**
- Modify: `collector/tests/test_scheduler.py`
- Modify: `backend/tests/test_collector_e2e.py`
- Modify: `backend/tests/test_collector_ingestion.py`
- Modify: `docs/architecture.md`
- Modify: `docs/data-sources.md`
- Modify: `docs/configuration.md`

**Interfaces:**
- Consumes: 前九个任务的共享接口
- Produces: 不依赖真实交易所的可重复端到端验收

- [ ] **Step 1: 增加 Collector 合成 provider E2E**

fake provider 两轮返回：

```text
第 1 轮: OPEN LONG 0.10, checkpoint.recordId=1 -> baseline, outbox=0
第 2 轮: OPEN LONG 0.10 + ADD LONG 0.05, checkpoint.recordId=2 -> outbox=1
第 3 轮: 与第 2 轮相同 -> outbox 仍为 1
第 4 轮: login_required -> checkpoint.recordId=2, position=STALE
```

断言 `externalId` 包含固定 account ID、source ID 和 revision，不包含昵称。

- [ ] **Step 2: 增加 Backend 上传到私有 Signal E2E**

向 `/api/v1/collector/posts` 上传一条 `binance_copy` 规范化事件，然后运行 analysis queue：

```python
from unittest.mock import Mock

assert upload.json()["items"][0]["status"] == "accepted"
model = Mock()
model.structure.side_effect = AssertionError("LLM must not run")
assert process_pending_posts(session, model) == 1
model.structure.assert_not_called()
assert client.get("/api/signals", headers=headers).json()["items"] == []
private_items = client.get("/api/admin/signals", headers=headers).json()["items"]
assert len(private_items) == 1
assert private_items[0]["structuredStatus"] == "deterministic"
assert private_items[0]["actionable"] is True
```

- [ ] **Step 3: 更新架构和数据源文档**

文档必须明确：

```text
共享 foundation 已实现但真实 provider 仍受 POC 门禁
固定账号 ID 和 10 分钟调度
baseline 不通知
private 数据隔离
deterministic structurer 不调用 LLM
空响应/登录失效不代表平仓
```

不要把未完成的 OKX/Binance provider 写成“已上线”。

- [ ] **Step 4: 运行全量验证**

Run:

```bash
cd backend && pytest -q
PYTHONPATH=collector pytest -q collector/tests
cd frontend && node --experimental-strip-types --test tests/*.test.mjs
cd frontend && npx tsc --noEmit
cd frontend && npm run build
git diff --check
```

Expected: 所有命令成功；0 test failures；0 TypeScript errors；build 成功；无 whitespace errors。

- [ ] **Step 5: 检查敏感信息和变更范围**

Run:

```bash
git diff --name-only
! git diff | rg -ni 'authorization:|bearer [a-z0-9]|cookie=|password=|api[_-]?key='
git status --short
```

Expected: 敏感值扫描 0 matches；未跟踪文件 `1` 未暂存；没有真实 exchange response、profile 或 session 文件。

- [ ] **Step 6: 提交共享 foundation 验收**

```bash
git add collector/tests/test_scheduler.py backend/tests/test_collector_e2e.py backend/tests/test_collector_ingestion.py docs/architecture.md docs/data-sources.md docs/configuration.md
git diff --cached --check
! git diff --cached | rg -ni 'authorization:|bearer [a-z0-9]|cookie=|password=|api[_-]?key='
git commit -m "test: verify private trade monitoring foundation"
```

---

## Provider Plan Gate

完成本计划只代表共享 foundation 可运行，不代表已能抓取交易所真实数据。下一步严格依据 `2026-08-09-exchange-private-trade-source-poc.md` 的实际产物执行：

```text
binance_copy supported -> 根据已脱敏 Binance fixture 编写并审核独立 provider implementation plan
okx_orbit supported -> 根据已脱敏 OKX fixture 编写并审核独立 provider implementation plan
任一 unsupported -> 停止该来源并向用户确认，不创建猜测性 provider
```

Provider 计划必须写出真实 host/path/method、请求分页结构、响应字段映射、登录失效识别和 fixture-based tests；不得保留未定义字段映射或空实现。
