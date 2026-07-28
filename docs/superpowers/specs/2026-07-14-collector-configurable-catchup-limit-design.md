# Collector 可配置停机补抓上限设计

## 目标

Collector 已有本地 checkpoint 时，重启或恢复运行后补抓 checkpoint 之后的帖子：

- 新帖不超过配置上限时全部补抓。
- 新帖超过配置上限时只补抓最近的若干条。
- 默认上限为 5，可通过 `CATCHUP_FETCH_LIMIT` 调整。
- 没有 checkpoint 的首次初始化仍只抓 `INITIAL_FETCH_LIMIT=1` 条。

## 数据流

1. Collector 从 SQLite `subscription_state` 读取订阅 checkpoint。
2. checkpoint 不存在时，provider 使用 `INITIAL_FETCH_LIMIT`。
3. checkpoint 存在时，provider 使用 `CATCHUP_FETCH_LIMIT`。
4. X 与 Binance Square provider 都必须返回按时间从旧到新排序、数量不超过 limit 的结果。
5. `CollectorStore.record_fetch` 在同一 SQLite 事务中先写 Outbox，再把 checkpoint 推进到本批最新帖子。
6. 上传失败不回退 checkpoint；待上传帖子留在 Outbox，由下一轮按现有退避机制重试。

如果 checkpoint 后存在超过上限的帖子，更老的超额部分会被永久跳过，checkpoint 直接推进到最近一批中的最新帖子。这是用户确认的方案 A。

## 配置

新增 Collector 私有配置：

```dotenv
CATCHUP_FETCH_LIMIT=5
```

约束：

- 默认值为 5。
- 小于 1 的值按 1 处理。
- 只存在于本机 Collector 配置，不需要修改公网 API 或生产数据库。
- 修改后需要重启 launchd Collector 才会生效。

## 测试

- 配置测试覆盖默认值 5 和环境变量覆盖。
- Scheduler 测试覆盖：无 checkpoint 使用 1；已有 checkpoint 使用 5；自定义配置能够覆盖 5。
- 重启测试覆盖：SQLite checkpoint 在 Collector 进程重启后仍触发补抓。
- X provider 测试覆盖：即使上游返回超过 limit 的数据，也只保留最新 limit 条。
- 保留现有 Outbox 重试、provider 隔离和 heartbeat 测试。

## 部署与验收

- 修改本机 `collector/.env` 后重启 launchd Collector。
- 首轮日志应显示每个订阅 `success`、`skipped` 或 `failed`。
- 验证 Collector 状态为 running，远端 heartbeat healthy，X authenticated，Binance Square healthy，Outbox 0。
- 不重建 API/Web，不修改生产订阅、checkpoint、历史信号或 Nginx。
