# Architecture

## 运行边界

- 本机 `collector-agent`：OpenCLI X、Binance Square、Binance Copy 成交记录、SQLite checkpoint/Outbox/交易 ledger、provider 告警。
- 公网 `api`：collector token 验证、MySQL 原帖与分析队列、ntfy。
- 公网 `web`：只使用 httpOnly 管理员 Cookie 访问已保护的 Dashboard API；私有交易信号只在管理端入口展示。

```text
OpenCLI / Binance Square / Binance Copy order history
        -> 本机 Collector + SQLite Outbox
        -> HTTPS Collector Bearer token
        -> FastAPI + MySQL pending queue
        -> 普通内容调用模型 / 交易事件确定性结构化
        -> public Signal / private admin Signal + assets/tags + ntfy
        -> 受登录保护的 Next.js Dashboard
```

`raw_posts` 以 `(platform, external_id)` 去重；上传先持久化为 `pending`，分析循环随后最多写入一条 Signal。`notification_events` 以 `(signal_id, notification_rule_id)` 去重。每个订阅分别按 `interval_minutes` 调度，正在执行的订阅不会重入，本轮开始时间加间隔才是下一次检查时间。

## Binance Copy 交易链路

`binance_copy` 订阅以固定 `portfolioId` 标识账号，当前实现仅支持 Binance，不注册 OKX provider。交易订阅固定为 1 分钟和 `private`；首轮抓取只把最近记录写入本机 ledger、建立低置信度基线，不产生 Outbox 或通知。后续新记录按 `accountId:sourceRecordId:revision` 形成稳定外部 ID，经历史账本推导 `OPEN/ADD/REDUCE/CLOSE` 和 `positionAfter`。同一次订阅采集中的新成交共享 `collectionBatchId`，并携带批次总笔数和按品种、方向计算的仓位前后差异。交易订阅的默认通知阈值为“低”，确保当前 `history_complete=false` 的新增事件在配置 ntfy 后仍可通知；普通订阅继续默认“中”。

交易事件上传后仍逐笔复用 `RawPost`、Signal、asset/tag，以保留完整操作记录，但通知会等待同批所有 Signal 就绪后再合并。只有方向、数量、推测开仓均价或杠杆发生变化且 `positionChanges` 非空时才发送一条 ntfy；现价、预计盈亏或账户保证金的单独刷新不触发。常规 `/api/signals`、Signal 详情、KOL、资产和统计查询排除 private 订阅；只有需管理员登录的 `/api/admin/signals` 可以读取。管理页复用常规卡片、筛选、分页和 60 秒非阻断刷新。这里的 `private` 是应用内可见性边界，不表示 Binance 当前首屏 BAPI 强制登录。

## 安全边界

管理员 Cookie 不能调用 Collector API，Collector token 也不能调用 Dashboard API。X Cookie、Chrome profile 和 Collector 明文 token 只保留在采集机；公网服务只保存 token 的 SHA-256。原始内容始终保存在 `raw_posts.raw_text`，翻译与摘要不会覆盖原文。

Binance Copy provider 当前使用匿名只读请求，不发送或持久化 Cookie、Authorization、密码、验证码及浏览器 profile。内部 BAPI 没有官方版本稳定性保证，因此只允许固定 host/path、固定响应上限和严格字段校验；原始响应体不写入日志。

## 故障语义

采集与 checkpoint 入 Outbox 在同一 SQLite 事务中。上传网络失败保留 `pending` 并指数退避，服务端 `accepted`/`duplicate` 才删除，`invalid` 进入死信。单个 provider 失败不会阻塞其他 provider 或心跳；分析失败保留原帖和重试计数。

Binance Copy 的成功空响应、请求失败或访问受限都不等于平仓。请求/访问失败保留 checkpoint 并把已有推测仓位标记为 `STALE`；最近 100 条重叠窗口找不到旧 checkpoint 时不推进 checkpoint，并把仓位降为 `UNKNOWN`。只有明确的减少或关闭成交事件才能推导减仓/平仓。
