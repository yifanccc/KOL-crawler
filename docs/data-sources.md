# Data Sources

## X

本机执行已验证命令：`opencli twitter tweets <handle> --limit <n> --format json`。首次登录使用 `opencli twitter login`；Chrome profile 与 Cookie 永不上传。登录/验证失败时 Provider 返回 `login_required`，不推进 checkpoint。

验证登录态：

```bash
opencli twitter --help
opencli twitter tweets senerity --limit 1 --format json
```

X snowflake checkpoint 按整数比较，过滤重复后按时间从旧到新进入 Outbox。Provider 同时兼容 ISO 时间和 OpenCLI v1.8.5 的 `Sat Jul 11 10:45:46 +0000 2026` 格式，并按真实字段把 `author` 作为 handle、`name` 作为显示名。超时、命令缺失或畸形 JSON 只改变 provider 健康状态，不输出环境变量、Cookie、Authorization header 或 profile 路径。

## Binance Square

`binance_square` 只解析公开页面，默认模板为 `https://www.binance.com/en/square/profile/{handle}`，可通过 `BINANCE_SQUARE_PROFILE_URL` 覆盖。它使用独立 checkpoint；HTTP 失败或页面结构变化记录为 `failed`，不阻塞 X、Outbox 上传或心跳。

## Binance Copy

`binance_copy` 读取目标带单组合的最近成交记录。熬鹰资本的固定 Portfolio ID 是 `5075281354358777856`；订阅身份使用该 ID，昵称只用于展示，不能参与去重键。当前 provider 请求网站内部 BAPI：

```text
POST https://www.binance.com/bapi/futures/v1/friendly/future/copy-trade/lead-portfolio/order-history
```

请求体只包含 `portfolioId`、最近 30 天的 `startTime`/`endTime` 和固定 `pageSize=100`。当前首屏契约已在未登录上下文验证，因此 collector 不发送或保存 Binance Cookie、Authorization 或浏览器 profile。该路径不是 Binance 对外承诺稳定的开发者 API；provider 会限制响应为 2 MB，并严格校验顶层成功状态、分页字段和每条记录的类型。完整字段证据与脱敏样例见 [来源 POC](research/2026-08-09-exchange-private-trade-source-poc.md)。

Binance 响应没有稳定订单 ID。provider 使用成交时间、标的、方向、仓位方向、类型、数量和均价生成 `sourceRecordId`，再对可修订成交字段生成 `revision`；所有数值在业务层使用 `Decimal`。`BUY LONG`/`SELL SHORT` 先映射为 `INCREASE`，`SELL LONG`/`BUY SHORT` 映射为 `DECREASE`，本地账本再结合此前推测仓位产生 `OPEN/ADD/REDUCE/CLOSE`。仓位增减只使用 `executedQty` 的币数；成交金额、标记价格和保证金不参与数量账本。

每次 10 分钟轮询都重叠读取最近 100 条：

- 第一次成功读取只建立基线，不上传信号、不通知，也不声称获得完整持仓。
- 后续只为新增的 `(sourceRecordId, revision)` 生成事件；重复响应保持幂等。
- 配置 `positionStartAt` 后，起算时刻被明确视为空仓。此后的成交币数从 0 累计，平仓最多扣到 0；超出当前推算数量的部分不生成反向仓位，也不把显式空仓基线污染为 `UNKNOWN`。
- 成功空响应不生成平仓事件；访问失败保留 checkpoint，并把已有仓位标为 `STALE`。
- 旧 checkpoint 不在重叠窗口时视为历史缺口，不推进 checkpoint，并把仓位标为 `UNKNOWN`。
- 未配置 `positionStartAt` 的订阅仍按不完整历史处理，矛盾数量保持 `UNKNOWN`。推测持仓只用于解释成交序列，不代表交易所实时仓位。

provider、账本、私有 Signal 和管理端页面已完成本地实现与自动化验证，但截至 2026-08-12 尚未部署到生产。OKX 不在当前运行范围。

系统只识别 A 股代码/名称与其它标的标签，不采集 A 股社区内容。
