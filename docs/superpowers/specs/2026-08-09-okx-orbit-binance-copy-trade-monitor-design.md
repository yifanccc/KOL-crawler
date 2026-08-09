# OKX Orbit 与 Binance Copy 交易变化监控设计

Date: 2026-08-09

Status: Accepted（方案 A）

## 1. 目标

在现有 KOL-crawler 中新增两类只读交易来源，每个订阅约每 10 分钟抓取一次，并尽量复用当前订阅、Collector 调度、SQLite checkpoint/outbox、Provider Health、后端 RawPost/Signal、ntfy 和 Dashboard 能力：

- `okx_orbit`：固定监控十老板，Orbit User ID `872838143249428480`。
- `binance_copy`：固定监控熬鹰资本，Portfolio ID `5075281354358777856`。

两类来源都以“交易记录变化”为输入。Binance 不依赖公开持仓接口，而是从连续交易记录推测当前持仓；OKX 仅在登录态完整交易记录接口通过 POC 后启用。

## 2. 已确认的产品决定

- 采用方案 A：扩展现有流水线，不新建独立交易监控系统。
- `okx_orbit`、`binance_copy` 是独立平台类型；`binance_copy` 不得复用或混入 `binance_square`。
- 两个订阅均使用 `interval_minutes = 10`。
- 沿用现有调度语义：首次启动可立即执行，之后以下发的 `intervalMinutes` 计算下一次检查；抓取耗时会使实际间隔略长于 10 分钟，不承诺严格整点。
- 用不可变平台 ID 定位账户，昵称只用于展示。
- 交易方向、数量、价格、杠杆和持仓变化由确定性代码解析，不交给 LLM 推断。
- 首次成功抓取只建立基线和推测持仓，不发送历史交易通知。
- OKX 完整交易记录接口若无法安全、稳定复用，必须暂停并向用户确认；不得自动降级为 Orbit 公开动态快照。
- 所有经登录态取得的交易数据默认视为私有数据，不进入公开 Signal API 或公开 Dashboard。

## 3. 已知数据源边界

### 3.1 OKX Orbit

- 固定主页：`https://www.okx.com/zh-hans/orbit/user/872838143249428480`。
- 网页已确认能看到十老板的公开动态以及主动分享的交易快照，但这些快照不代表完整交易记录。
- OKX 当前 FAQ 说明 Orbit 支持 Web 和 App，用户可以控制 Trading Record 的公开范围：`https://www.okx.com/en-us/help/okx-orbit-faq`。
- 手机 App 中可见的交易记录可能使用登录态内部接口、App 专用签名或设备绑定；具体接口、分页、稳定记录 ID 和鉴权方式尚未完成 POC。

因此，`okx_orbit` 的实施前置条件是先完成只读网络 POC。公开动态抓取不属于本设计的隐式 fallback。

### 3.2 Binance Copy Trading

- 固定 Portfolio ID：`5075281354358777856`。
- 目标页面：`https://www.binance.com/en/copy-trading/lead-details/5075281354358777856`。
- Binance 官方 Copy Trading API 主要面向本人账户；第三方或私域带单员记录依赖网站内部 BAPI，属于未公开稳定契约。
- 用户可在本机浏览器中完成登录。Collector 复用受控浏览器上下文发起只读请求，不导出 Cookie，也不保存密码或验证码。

## 4. 范围与非目标

### 4.1 首版范围

- 后台管理中创建、展示和启停 `okx_orbit`、`binance_copy` 订阅。
- 每 10 分钟抓取新的交易记录，并通过 checkpoint、重叠查询和唯一键去重。
- 生成 `OPEN`、`ADD`、`REDUCE`、`CLOSE`、`REVERSE`、`CORRECTION` 交易事件。
- 从连续记录维护本机推测持仓与置信度。
- 将新交易事件送入现有 RawPost/Signal/ntfy 流水线。
- 在登录保护的管理端展示私有交易信号，复用现有 Signal 卡片和筛选能力。
- Provider 登录失效、接口受限或响应结构变化时告警，且不推进 checkpoint。

### 4.2 非目标

- 下单、跟单、撤单或任何交易所写操作。
- 发现或搜索同名 KOL；两个目标均使用固定 ID。
- 通过昵称、头像或搜索结果重新定位账户。
- 手机 UI 自动点击、OCR 或定时截图采集。
- 在未确认前用 Orbit 公开动态快照替代完整交易记录。
- 严格实时或低于 10 分钟的监控。
- 将推测持仓包装成交易建议、投资建议或确定事实。
- 首版建设独立的组合管理、收益统计或回测系统。

## 5. 总体架构

```text
Admin Subscription
  platform + accountId + handle + intervalMinutes=10
                    |
                    v
Local Collector Scheduler
  ProviderTarget -> okx_orbit / binance_copy provider
                    |
                    v
Provider-validated normalized trade_events
  -> deterministic position inference (local SQLite)
  -> CollectedPost + sanitized rawPayload
                    |
                    v
Existing SQLite Outbox -> Collector Upload API
                    |
                    v
RawPost -> deterministic trade structurer -> Signal
                    |                         |
                    v                         v
        authenticated admin feed          ntfy

Regular Signal API / Dashboard
  -> always excludes private-source subscriptions
```

新增逻辑集中在来源适配、交易事件标准化、推测持仓和私有可见性；上传重试、RawPost 去重、资产关联、通知事件和 Provider Heartbeat 继续复用现有实现。

## 6. 订阅与接口契约

### 6.1 Subscription

复用已有 `subscriptions.platform_account_id`，并新增 `visibility`：

```text
platform_account_id: string | null
visibility: public | private
```

规则：

- `x`、`binance_square` 保持当前行为，`accountId` 可为空，默认 `visibility=public`。
- `okx_orbit`、`binance_copy` 必须提供仅包含数字的 `accountId`，长度为 8-32；服务端强制 `visibility=private`。
- 新增数据库唯一约束 `(platform, platform_account_id)`；MySQL 允许旧平台的 `NULL` 共存。
- `accountId` 创建后不可通过普通 PATCH 修改；定位错误时删除并重建订阅，避免无意切换监控对象。
- `handle` 继续保存 `十老板`、`熬鹰资本` 等展示名，不能作为抓取定位键。

### 6.2 Admin API

`POST /api/admin/subscriptions` 增加可选字段：

```json
{
  "platform": "okx_orbit",
  "handle": "十老板",
  "accountId": "872838143249428480",
  "intervalMinutes": 10
}
```

订阅返回值增加只读字段 `accountId` 和 `visibility`。这是向后兼容的增量字段；现有客户端可忽略。

### 6.3 Collector Config API

`GET /api/v1/collector/config` 的每个订阅增加可选字段：

```json
{
  "id": 21,
  "platform": "binance_copy",
  "handle": "熬鹰资本",
  "accountId": "5075281354358777856",
  "intervalMinutes": 10,
  "enabled": true
}
```

现有字段和含义不变。

### 6.4 ProviderTarget

Collector 内部用结构化目标替代语义含混的单个 `handle` 参数：

```text
ProviderTarget
  subscription_id: int
  platform: str
  account_id: str | null
  handle: str
```

Provider 接口统一为：

```text
fetch(target, checkpoint, limit) -> ProviderFetchResult
```

`ProviderFetchResult` 是判别联合，避免把交易记录伪装成帖子：

```text
PostFetchResult
  kind: posts
  posts: list[CollectedPost]
  candidate_checkpoint: string | null

TradeEventFetchResult
  kind: trade_events
  events: list[TradeEvent]
  candidate_checkpoint: string | null
```

现有 X/Binance Square provider 返回 `PostFetchResult`，只使用 `target.handle`；新 provider 必须使用 `target.account_id`，在 provider 边界完成第三方响应 schema 校验与来源字段映射，并返回 `TradeEventFetchResult`。Scheduler 先检查 Provider Health，再把帖子交给现有 `record_fetch`，或把规范化事件交给独立 `trade_reconciler` 和 `record_trade_fetch`。两个 result 分支不能同时携带数据。

## 7. 标准化交易事件

Provider 校验并映射来源记录，向 Collector 返回统一的 `TradeEvent`：

```text
schema_version: 1
platform: okx_orbit | binance_copy
account_id: string
source_record_id: string
revision: string
action: OPEN | ADD | REDUCE | CLOSE | REVERSE | CORRECTION
symbol: string
position_side: LONG | SHORT | UNKNOWN
quantity: decimal | null
price: decimal | null
leverage: decimal | null
event_time: datetime
observed_at: datetime
position_after:
  side: LONG | SHORT | FLAT | UNKNOWN
  quantity: decimal | null
  confidence: HIGH | MEDIUM | LOW | UNKNOWN
source_url: string | null
```

约束：

- 金额和数量在内存、SQLite 与 JSON 序列化中使用十进制字符串，不使用二进制浮点数。
- `source_record_id` 优先使用交易所稳定记录 ID；若 POC 证明没有稳定 ID，才允许用经过文档化的核心字段哈希。
- `revision` 是影响交易语义字段的规范化哈希。相同记录、相同 revision 完全幂等；同一记录发生实质修改时生成 `CORRECTION`。
- 上传使用的 `externalId` 为 `{accountId}:{sourceRecordId}:{revision}`，避免不同账户间冲突。
- `rawPayload` 只包含该标准化事件和经过字段白名单过滤的来源记录，不含 Cookie、Authorization、设备标识或完整网络响应头。

## 8. Checkpoint、重叠抓取与首次基线

Checkpoint 继续保存在 Collector SQLite 的 `subscription_state.checkpoint`，内容改为版本化 JSON 字符串：

```json
{"v":1,"eventTime":"2026-08-09T10:00:00Z","recordId":"123456"}
```

抓取规则：

1. 首次抓取读取足以建立当前推测持仓的可用历史，写入本机交易事件表和持仓表。
2. 首次抓取不创建 outbox 消息，不发送历史通知；日志明确记录 `baseline_created`。
3. 后续每次抓取除 checkpoint 之后的新记录外，还读取一个固定、受限的重叠窗口，以处理延迟出现或后来修订的记录。
4. 重叠窗口大小由各 provider 的 POC 结果固定在代码和测试夹具中，不作为首版管理端配置。
5. SQLite 在一个事务中完成来源记录 upsert、受影响标的持仓重算、CollectedPost 入 outbox 和 checkpoint 推进。
6. schema 校验、持仓重算或 outbox 写入任一步失败，整笔事务回滚，checkpoint 保持不变。

新增本机表：

```text
trade_events
  subscription_id
  source_record_id
  revision
  event_time
  normalized_json
  first_observed_at
  last_observed_at
  UNIQUE(subscription_id, source_record_id, revision)

position_estimates
  subscription_id
  symbol
  side
  quantity
  confidence
  status
  as_of_event_time
  stale_since
  updated_at
  PRIMARY KEY(subscription_id, symbol)
```

`status` 取 `ACTIVE | FLAT | UNKNOWN | STALE`；Provider 失败时不改写最后一次 side/quantity，只把状态转为 `STALE` 并记录 `stale_since`。

Outbox 仍使用现有 `outbox_posts`，不另建第二套上传队列。

## 9. 持仓推测规则

- 初始状态必须是 `UNKNOWN`，不能默认 `FLAT`。
- 只有连续、可核对且包含完整数量的记录才能产生 `HIGH` 置信度。
- 缺少数量但方向和动作明确时，可维护方向状态，置信度最多为 `MEDIUM`，数量为 `null`。
- 出现记录缺口、分页不完整或无法解释的修订时，受影响标的降为 `UNKNOWN`，不得继续输出精确数量。
- 空响应、网络失败、登录失效或页面隐藏均不代表平仓。
- `CLOSE` 只有在来源记录明确表示该仓位关闭，或完整数量运算严格归零时成立。
- `REVERSE` 必须能拆解为旧方向归零和新方向建立；否则标记为 `CORRECTION` 并降置信度。
- 每次新记录或修订到达时，从本地规范化事件重算受影响标的，避免重复抓取导致累计数量错误。

推测结果必须在摘要中写明“推测持仓”和置信度，不能用“当前实际持仓”措辞。

## 10. 接入现有 RawPost、Signal 与通知

每个新增或实质修订的 `TradeEvent` 生成一个 `CollectedPost`：

- `platform`：`okx_orbit` 或 `binance_copy`。
- `external_id`：账户 ID、来源记录 ID 与 revision 的组合。
- `author_handle`：展示昵称。
- `published_at`：交易事件时间，而非抓取时间。
- `raw_content`：确定性中文摘要。
- `raw_payload`：标准化 TradeEvent 与白名单来源字段。

后端分析队列按平台分流：

- `x`、`binance_square` 保持现有 LLM/heuristic structurer。
- `okx_orbit`、`binance_copy` 使用 deterministic trade structurer，校验 `rawPayload.schemaVersion` 后直接构造现有 `Signal`。
- `structured_status` 写为 `deterministic`。
- 开仓、加仓和反手使用结果方向映射 `bullish`/`bearish`。
- 减仓和平仓使用 `neutral`，但 `actionable=true`，确保仍可按通知规则发送。
- `tags` 至少包含来源和动作，例如 `交易记录`、`开仓`、`推测持仓`。
- 所有价格、数量和方向必须来自标准化事件，不调用模型补全缺失字段。

ntfy 复用现有通知事件和重试边界，新增平台标题 `OKX Orbit`、`Binance Copy`。通知只包含确定性摘要、标的、动作、方向和置信度，不包含原始私域响应。

## 11. 私有可见性

`okx_orbit`、`binance_copy` 的订阅强制为 `private`：

- 现有常规 `/api/signals`、KOL 页面、资产页面和统计总数必须排除 private 订阅；即使当前部署整体要求登录，也不能把私域数据混入常规信号流。
- 新增登录保护的 `GET /api/admin/signals`，返回与常规 Signal API 相同的分页/筛选结构，以复用前端数据类型和卡片。
- 管理端增加“私有交易信号”入口；不复制一套新的卡片样式。
- RawPost 和 Signal 可以保存在用户自己的后端数据库，但所有读取入口必须经过现有管理员认证。
- ntfy 仅发送到订阅已配置的服务器和 topic；不把登录态或原始来源记录放入消息。

## 12. 登录态与安全边界

- 用户只在交易所官方页面或 App 中手动登录；Collector 不接收密码、验证码或恢复码。
- 若 OKX POC 需要在手机安装抓包证书、代理配置或其他设备级组件，必须先单独说明影响并取得用户确认；当前设计批准不等于授权安装。
- 浏览器来源使用专用本机 profile 目录，目录权限为仅当前用户可读写，并加入 `.gitignore`。
- 不把 Cookie、Authorization、设备签名或浏览器 profile 内容写入环境变量、日志、SQLite payload、后端或 Git。
- 请求主机、路径和方法使用 provider 内固定白名单；不存在“传入任意 URL 后抓取”的接口。
- 即便来源接口使用 POST，也只允许经 POC 确认的只读查询路径；任何下单、跟单、设置或修改接口都不实现。
- 外部响应限制体积、设置超时并执行严格 schema 校验；未知字段可以保留在本机诊断摘要中，但不驱动业务逻辑。
- 日志只记录平台、订阅 ID、健康状态、记录数量和错误类别，不记录响应正文或鉴权材料。

## 13. Provider Health 与错误语义

继续使用现有成功状态：

- `healthy`
- `authenticated`

新增或明确使用的失败状态：

- `login_required`：登录过期或当前浏览器/App 会话未登录。
- `access_limited`：账号无权查看目标私域记录、频率限制或风控拦截。
- `schema_changed`：响应成功但不符合已验证 schema。
- `unsupported`：POC 证明接口依赖无法安全复用的设备签名或其他不可满足条件。
- `failed`：网络、浏览器或未分类运行错误。

失败状态统一行为：

- 不创建交易事件。
- 不把空结果解释为无交易或已平仓。
- 不推进 checkpoint。
- 保留上一次推测持仓，但标记为 stale；前端不得显示为实时状态。
- Heartbeat 变为 degraded，并沿用现有告警冷却机制。

`unsupported` 对 OKX 是人工决策门禁：停止该订阅实施或运行，向用户报告证据并确认下一步，不自动启用公开快照 provider。

## 14. OKX POC 门禁

实现正式 `okx_orbit` provider 前必须完成以下验证：

1. 在用户已经登录的手机 App 中，仅观察打开十老板“交易记录”页面产生的网络请求。
2. 确认精确主机、路径、方法、鉴权依赖、分页/游标和响应 schema。
3. 用至少 20 条连续可见记录（不足 20 条时用全部）逐项核对标的、方向、动作、数量、价格、杠杆和时间。
4. 间隔 10 分钟执行两次只读抓取，验证相同记录 ID 稳定且增量/修订可区分。
5. 验证登录失效能被识别为 `login_required`，而不是空列表。
6. 证明自动化不需要保存密码、验证码、导出 App 会话或调用写接口。

若第 2、4 或 6 项无法满足，POC 结论为 `unsupported`，停止后续 OKX 实现并与用户确认。此时不能自行切换到公开动态快照、OCR 或手机自动点击。

## 15. 测试设计

### 15.1 Collector

- 两个 provider 的成功、空页、分页、登录失效、权限限制和 schema 变化夹具。
- Scheduler 向 provider 传递固定 `accountId`，并在成功后按 10 分钟安排下一次检查。
- 首次基线写入事件和推测持仓，但 outbox 为 0。
- OPEN、ADD、REDUCE、CLOSE、REVERSE、CORRECTION 的确定性推测用例。
- 重叠窗口重复记录不重复累计、不重复通知。
- 空响应和 Provider Health 失败不清空持仓、不推进 checkpoint。
- SQLite 事务失败时事件、持仓、outbox 和 checkpoint 一起回滚。
- Collector 重启后从本地 ledger 恢复，不重复发送旧记录。

### 15.2 Backend

- 新平台和 `accountId` 的平台相关校验。
- Collector config 的 `accountId` 增量契约。
- deterministic trade structurer 不调用模型，并拒绝非法 schema/version。
- private Signal 不出现在常规列表、KOL、资产和统计 API。
- 未登录不能读取 Admin Signal API。
- 交易动作、stance、actionable、置信度、平台标题和 ntfy 文案映射。
- RawPost 与 Signal 的重复上传仍保持幂等。

### 15.3 Frontend 与端到端

- Admin 表单只对新平台要求账号 ID，并显示固定 ID 而不是只显示昵称。
- 私有交易信号复用现有卡片、分页和筛选，不出现在常规首页。
- 注入一条交易夹具后，只生成一条 private Signal 和一条 ntfy 事件。
- 浏览器验证常规页面不会请求或渲染 private Signal。

## 16. 验收标准

- 十老板和熬鹰资本均以固定平台 ID 建立独立订阅，间隔为 10 分钟。
- OKX 只有在 POC 全部通过后才启用；失败时停下并请求用户确认。
- 首次抓取无历史通知，第二次起只通知新增或实质修订事件。
- Binance 不需要公开持仓接口，也能从测试夹具和连续真实记录给出带置信度的推测持仓变化。
- 重复记录、进程重启和 outbox 重试不会重复推送。
- 登录失效、空响应和接口结构变化不会产生“已平仓”误报。
- 交易数值不经过 LLM，来源缺失的字段保持未知。
- 私有交易记录和信号不会出现在任何常规 Signal API、页面或统计中，只能通过管理端私有入口读取。
- 现有 X、Binance Square 订阅行为和 Dashboard 不回归。

## 17. 实施顺序与停止条件

1. OKX 与 Binance 只读 POC，固化脱敏夹具和接口边界。
2. 订阅 `accountId`、`visibility`、Collector config 和唯一约束。
3. `ProviderTarget`、本机交易事件 ledger、推测持仓与事务边界。
4. `binance_copy` provider 与登录态健康检查。
5. 在 OKX POC 通过的前提下实现 `okx_orbit` provider。
6. deterministic trade structurer、ntfy 映射和私有 API 过滤。
7. Admin 私有信号入口与端到端验收。
8. 创建两个 10 分钟订阅并进行观察性启用。

停止条件：

- OKX POC 为 `unsupported`。
- Binance 登录态无法在不导出 Cookie/凭据的情况下运行。
- 数据源不提供稳定记录 ID，且无法构造经重复抓取验证的确定性指纹。
- 无法在常规 API 层证明 private 数据被完整排除。

触发任一停止条件时，不采用替代抓取方式，不扩大权限，先向用户报告证据并确认。

## 18. 部署与回滚

- 复用已有 nullable `platform_account_id` 列；数据库迁移只新增其组合唯一约束和有默认值的 `visibility`，不删除现有数据。
- 新 provider 先在禁用订阅上完成健康检查，再分别启用；不要同时开启两个未观察来源。
- 回滚时先禁用对应订阅，再回滚 Collector/API/Web；保留本机 ledger 和后端 RawPost/Signal 以便审计，不自动删除。
- 旧客户端可忽略新增 API 字段；禁用新订阅后，现有 X/Binance Square 流程继续运行。

## 19. 被否决的方案

### 独立交易监控子系统

会重复建设调度、健康检查、上传重试、通知和 UI，首版收益不足以覆盖复杂度。

### 手机 UI 自动化或 OCR

缺少稳定记录 ID、难以可靠分页、容易受布局和风控影响，不适合长期每 10 分钟运行。

### 自动使用 Orbit 公开动态快照降级

公开快照是用户主动分享的局部信息，不能代表完整交易记录；自动降级会制造错误完整性预期，且违背已确认的人工确认边界。
