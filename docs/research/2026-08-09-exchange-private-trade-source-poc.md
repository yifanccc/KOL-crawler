# Exchange Trade Source POC

Date: 2026-08-09 / 2026-08-10 (Asia/Shanghai)

## Status

| Source | Status | Decision |
| --- | --- | --- |
| Binance Copy / 熬鹰资本 | `supported` | 支持每 10 分钟读取最近操作记录并推测持仓变化；首版必须保留本文中的 ID、分页和缺口限制。 |
| OKX Orbit / 十老板 | `not_run` | 网页只提供动态和持仓快照；App 交易记录抓取需要新增手机代理/证书能力，等待单独授权。 |

这里的 `supported` 只表示只读来源契约通过 POC，不等同于生产上线。截至 2026-08-12，Binance provider、10 分钟调度、推测持仓、私有 Signal 和管理端页面已在专属分支完成本地实现与自动化验证，但尚未部署；OKX 仍不在运行范围。

## Safety Boundary

- 所有观察均为官方页面或固定白名单路径上的只读查询。
- 用户只在 Binance 官方页面中手动登录；没有读取、复制或保存密码、验证码、Cookie、Authorization、设备签名或浏览器 profile。
- 没有保存真实响应体或 HAR。两次稳定性观察只在仓库外、权限为 `0700` 的临时目录中保存不可逆 SHA-256 指纹，单个文件权限为 `0600`。
- Git 夹具只保留来源字段名和类型，数量、价格、时间和标的均为固定测试值。

## Binance Copy: 熬鹰资本

### Read-only contract

- Target Portfolio ID: `5075281354358777856`
- Page: `https://www.binance.com/zh-CN/copy-trading/lead-details/5075281354358777856`
- Host: `www.binance.com`
- Method: `POST`
- Path: `/bapi/futures/v1/friendly/future/copy-trade/lead-portfolio/order-history`
- Content-Type: `application/json`

首次请求：

```json
{
  "portfolioId": "5075281354358777856",
  "startTime": 1783728000000,
  "endTime": 1786319999000,
  "pageSize": 20
}
```

后续页在相同请求中增加：

```json
{
  "indexValue": "<previous response data.indexValue>"
}
```

Binance 当前网页前端也使用上述路径，并把 `data.indexValue` 原样放入下一次请求。该路径是网站内部 BAPI，不是公开、带版本保证的官方开发者 API。

### Response schema and mapping

成功响应顶层字段为：

```text
code: string
message: null | string
messageDetail: null | object
success: boolean
data:
  list: array
  total: number
  indexValue: string
```

单条 `data.list[]` 的实测字段与类型：

| Source field | Type | Normalized meaning |
| --- | --- | --- |
| `orderUpdateTime` | number | `event_time`，Unix milliseconds |
| `orderTime` | number | 合成记录键的一部分 |
| `symbol` | string | `symbol` |
| `side` | string | `BUY` / `SELL` |
| `type` | string | 实测 `LIMIT` / `MARKET`，保留用于 ID 和诊断 |
| `positionSide` | string | `LONG` / `SHORT` |
| `executedQty` | number | `quantity`，进入业务层前转十进制字符串 |
| `avgPrice` | number | `price`，进入业务层前转十进制字符串 |
| `baseAsset` | string | 展示/校验字段 |
| `quoteAsset` | string | 展示/校验字段 |
| `totalPnl` | number | 不参与持仓数量、ID 或 revision |

动作映射只描述仓位方向上的增减，`trade_reconciler` 再根据此前推测仓位判断 `OPEN/ADD` 或 `REDUCE/CLOSE`：

| `side` | `positionSide` | Directional operation |
| --- | --- | --- |
| `BUY` | `LONG` | 增加多头敞口 |
| `SELL` | `LONG` | 减少多头敞口 |
| `SELL` | `SHORT` | 增加空头敞口 |
| `BUY` | `SHORT` | 减少空头敞口 |

响应没有杠杆字段，因此 `leverage = null`。网页首条记录的时间、标的、均价和成交数量均与响应逐项一致；最新操作页成功从 10 条加载到 20 条。

### Synthetic ID and revision boundary

响应不提供订单 ID。100 条连续样本中：

- 只用 `orderTime + symbol + side + type + positionSide` 时只有 81 个唯一键，并出现 8 组碰撞。
- 增加 `orderUpdateTime + executedQty + avgPrice` 后 100/100 唯一。
- `totalPnl` 不需要参与唯一性，且会引入与持仓无关的变化。

因此首版固定：

```text
sourceRecordId = sha256(
  "binance_copy_order_history:v1|" + canonical_json(
    orderTime,
    orderUpdateTime,
    symbol,
    side,
    type,
    positionSide,
    executedQty,
    avgPrice
  )
)

revision = sha256(canonical_json(
  orderUpdateTime,
  side,
  positionSide,
  executedQty,
  avgPrice
))
```

这是“不可变操作行”的合成键，不是交易所稳定订单 ID。若重叠窗口中旧哈希消失、相近时间出现新哈希，不能把它静默当成新成交；应把对应标的降为 `UNKNOWN` 并报告无法解释的修订。

### Ordering, pagination, empty and error semantics

- `data.list` 按 `orderUpdateTime` 降序；100 条样本中存在 9 个重复更新时间。
- `data.indexValue` 等于当前页最后一条记录的 `orderUpdateTime` 字符串。
- 未登录请求可直接读取首屏，`pageSize=100` 实测返回 100 条，且 `total` 大于 100。因此 Binance 首屏读取没有 `login_required` 语义。
- 未登录游标请求重复返回 `code="11012005"`、`success=false` 和通用“系统繁忙”消息；同一时段登录网页点击“更多”能从 10 条增加到 20 条。这证明游标有效，但尚未证明是哪一个登录态或前端请求头依赖导致差异。
- 合法空窗口返回 `code="000000"`、`success=true`、`data.list=[]`。
- 缺少 `portfolioId` 的无效请求返回 `code="200001054"`、`success=false`、`data=null`，可与合法空结果稳定区分。

不得创建虚假的 `binance_copy_login_required.json`：当前首屏接口在独立未登录上下文中成功，通用游标错误也不能可靠映射为登录失效。仓库只保留已验证的成功夹具 `collector/tests/fixtures/binance_copy_trade_records.json`。

### Ten-minute stability result

两次请求使用完全相同的时间范围、页大小和 ID 算法，只保存语义指纹：

| Observation | UTC time | Records | Snapshot hash |
| --- | --- | ---: | --- |
| 1 | `2026-08-09T15:53:53Z` | 20 | `e5ea4709234ecdeee7b2d9192a426589bd0e3b9abbe06ee815b33c2fde1a2661` |
| 2 | `2026-08-09T16:04:28Z` | 20 | `e5ea4709234ecdeee7b2d9192a426589bd0e3b9abbe06ee815b33c2fde1a2661` |

间隔 635 秒；20/20 个记录指纹保持不变，无新增、无窗口移出记录。

### Checkpoint and overlap rule

```text
checkpoint = {v: 1, eventTime: latest orderUpdateTime in UTC, recordId: sourceRecordId}
ordering = descending from source; normalize to ascending before reconciliation
overlap = latest 100 records on every 10-minute poll
empty page = successful response with code 000000 and list []
history_complete = false until authenticated pagination is implemented and verified
```

每次轮询必须确认旧 checkpoint 仍出现在最近 100 条中。若不在，说明 10 分钟内可能超过重叠容量或来源发生修订：不推进精确持仓，相关标的转为 `UNKNOWN`。首次基线不得声称完整历史持仓。

### Known gaps

- 内部 BAPI 可能无通知变化，provider 必须做严格 schema 校验。
- 没有交易所订单 ID，也没有可直接识别修订的字段。
- 没有杠杆字段。
- 匿名首屏足够支持滚动监控，但完整历史翻页仍需要复用受控浏览器会话或找到可复现的只读请求头边界。
- 产品仍可把这些信号标为 `private`，但这是本系统的可见性策略，不代表 Binance 首屏传输层要求登录。

## OKX Orbit: 十老板

### Current evidence

- Target Orbit User ID: `872838143249428480`
- Web page: `https://www.okx.com/zh-hans/orbit/user/872838143249428480`
- 网页标题和目标身份正确，但可访问标签只有“动态”；页面提供发帖附带的持仓快照，没有 App 中的完整“交易记录”。不能用这些快照替代用户指定的数据源。
- 本机没有已安装的 Proxyman、Charles 或 mitmproxy，没有 `rvictl`/ADB，也没有检测到已连接的 iOS/Android 设备。

因此 OKX 保持 `not_run`，尚不能写 `supported` 或 `unsupported`。下一步必须由用户单独批准设备级观察方式。

### Approval boundary

若手机是 iPhone，建议的下一次 POC 是：按 [Proxyman iOS Device](https://docs.proxyman.com/debug-devices/ios-device) 官方步骤安装 Proxyman，在同一网络下只代理该测试时段，用户手动安装并信任临时 CA profile，然后只打开 OKX 的十老板交易记录页面。风险与退出方式：

- 代理启用期间，Mac 上的调试工具可能看到手机其他 App 的 HTTPS 明文；测试时应关闭其他 App，并只保留 OKX 相关 host。
- 若 OKX 使用证书固定，[Proxyman 的 SSL 错误说明](https://docs.proxyman.com/troubleshooting/get-ssl-error-from-https-request-and-response)指出第三方 App 流量可能无法解密；本项目不绕过证书固定。此时结论为 `unsupported`。
- 结束后立即关闭 Wi-Fi 代理，删除手机中的 Proxyman profile/CA，并从 Mac 卸载工具；[Apple 的官方路径](https://support.apple.com/guide/personal-safety/review-and-delete-configuration-profiles-ips327569a75/1.0/web/1.0)是“设置 -> 通用 -> VPN 与设备管理 -> 选择 profile -> 删除 Profile”，然后重启设备。
- 不导出完整 HAR、App session、Cookie 或设备签名，只把目标只读路径、字段名/类型和脱敏交易样例带入仓库。

Android 需要不同的证书信任和连接步骤；在确认手机系统前不执行安装。

## Repository artifacts

- `collector/tests/fixtures/binance_copy_trade_records.json`: 脱敏成功响应，覆盖增加空头、减少多头和分页边界记录。
- `collector/tests/fixtures/binance_copy_login_required.json`: intentionally absent; no truthful signature was observed.
- OKX fixtures: absent while status is `not_run`.

## Sources inspected

- Binance target page and its live frontend asset `https://bin.bnbstatic.com/static/chunks/page-d6a9.58fd119d.js` (observed 2026-08-09).
- OKX target profile page (observed 2026-08-10 Asia/Shanghai).
- [Proxyman iOS device setup](https://docs.proxyman.com/debug-devices/ios-device) and [SSL error documentation](https://docs.proxyman.com/troubleshooting/get-ssl-error-from-https-request-and-response).
- [Apple configuration-profile removal documentation](https://support.apple.com/guide/personal-safety/review-and-delete-configuration-profiles-ips327569a75/1.0/web/1.0).
