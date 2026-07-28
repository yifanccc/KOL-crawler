# Architecture

## 运行边界

- 本机 `collector-agent`：OpenCLI X、Binance Square、SQLite checkpoint/Outbox、provider 告警。
- 公网 `api`：collector token 验证、MySQL 原帖与分析队列、ntfy。
- 公网 `web`：只使用 httpOnly 管理员 Cookie 访问已保护的 Dashboard API。

```text
OpenCLI / Binance Square
        -> 本机 Collector + SQLite Outbox
        -> HTTPS Collector Bearer token
        -> FastAPI + MySQL pending queue
        -> 中文结构化 Signal + assets/tags + ntfy
        -> 受登录保护的 Next.js Dashboard
```

`raw_posts` 以 `(platform, external_id)` 去重；上传先持久化为 `pending`，分析循环随后最多写入一条 Signal。`notification_events` 以 `(signal_id, notification_rule_id)` 去重。每个订阅分别按 `interval_minutes` 调度，正在执行的订阅不会重入，完成时间加间隔才是下一次检查时间。

## 安全边界

管理员 Cookie 不能调用 Collector API，Collector token 也不能调用 Dashboard API。X Cookie、Chrome profile 和 Collector 明文 token 只保留在采集机；公网服务只保存 token 的 SHA-256。原始内容始终保存在 `raw_posts.raw_text`，翻译与摘要不会覆盖原文。

## 故障语义

采集与 checkpoint 入 Outbox 在同一 SQLite 事务中。上传网络失败保留 `pending` 并指数退避，服务端 `accepted`/`duplicate` 才删除，`invalid` 进入死信。单个 provider 失败不会阻塞其他 provider 或心跳；分析失败保留原帖和重试计数。
