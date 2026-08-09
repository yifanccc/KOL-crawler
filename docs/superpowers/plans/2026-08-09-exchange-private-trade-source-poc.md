# Exchange Private Trade Source POC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不保存或外泄登录凭据的前提下，取得 Binance 熬鹰资本与 OKX 十老板交易记录的真实只读接口契约，并对每个来源给出 `supported` 或 `unsupported` 的可复核结论。

**Architecture:** POC 只观察用户手动登录后打开目标交易记录页面产生的只读请求，不接入生产 Collector。响应先留在仓库外临时目录，验证稳定 ID、分页、字段和登录失效语义后，才生成脱敏测试夹具与研究记录；OKX 若需要安装手机抓包证书或设备组件，必须先停下征得用户确认。

**Tech Stack:** Binance Web、OKX Mobile App、浏览器开发者工具或已获批的本机抓包工具、JSON、Markdown、`rg`、`jq`、Git。

## Global Constraints

- Binance 固定 Portfolio ID：`5075281354358777856`，展示名：`熬鹰资本`。
- OKX 固定 Orbit User ID：`872838143249428480`，展示名：`十老板`。
- 只观察交易记录查询；不调用下单、跟单、设置、关注或任何写接口。
- 用户只在交易所官方 UI 中手动输入密码、验证码或 Passkey；自动化不得读取、复制或记录这些值。
- 不导出 Cookie、Authorization、设备签名、完整 HAR、浏览器 profile 或 App 会话。
- 临时网络响应只能保存在 `mktemp -d` 创建的仓库外目录，POC 完成后清理。
- 提交到 Git 的夹具只能包含目标 KOL 的脱敏交易字段，不得包含当前登录用户的 UID、邮箱、手机号、IP、设备 ID、token 或 header。
- 两次稳定性观察间隔固定为 10 分钟。
- OKX 不通过时状态写为 `unsupported` 并向用户确认；不得自行改抓公开动态、截图或 OCR。
- 当前未跟踪文件 `1` 属于用户，任何 `git add` 命令都不得包含它。

---

### Task 1: 建立 POC 安全边界与临时工作区

**Files:**
- Create after observation: `docs/research/2026-08-09-exchange-private-trade-source-poc.md`
- Do not create in repo: raw HAR、Cookie 文件、浏览器 profile 或未脱敏响应

**Interfaces:**
- Produces: 仓库外临时目录绝对路径 `POC_CAPTURE_DIR`
- Produces: 研究记录中的统一状态 `not_run | supported | unsupported`
- Consumes: 已批准设计 `docs/superpowers/specs/2026-08-09-okx-orbit-binance-copy-trade-monitor-design.md`

- [ ] **Step 1: 验证分支与工作区边界**

Run:

```bash
git status --short --branch
git log -3 --oneline
```

Expected: 当前分支包含设计提交；`1` 仍为未跟踪文件，没有来源响应、HAR 或 profile 被跟踪。

- [ ] **Step 2: 创建仓库外临时目录**

Run:

```bash
POC_CAPTURE_DIR="$(mktemp -d -t kol-trade-poc.XXXXXX)"
chmod 700 "$POC_CAPTURE_DIR"
test "${POC_CAPTURE_DIR#"$PWD"/}" = "$POC_CAPTURE_DIR"
ls -ld "$POC_CAPTURE_DIR"
```

Expected: `POC_CAPTURE_DIR` 不在 `/Users/caoyifan/projects/KOL-crawler` 下，权限只允许当前用户访问。

- [ ] **Step 3: 记录允许提交的字段集合**

在执行笔记中固定以下白名单，之后生成夹具时只保留这些语义字段：

```text
targetAccountId
sourceRecordId
eventTime
symbol
action
positionSide
quantity
price
leverage
cursor/page metadata（仅来源分页所必需的字段）
```

Expected: 登录用户身份、请求 headers、Cookie 和设备字段不在白名单中。

---

### Task 2: 捕获 Binance 私域交易记录只读契约

**Files:**
- Create on supported result: `collector/tests/fixtures/binance_copy_trade_records.json`
- Create on supported result: `collector/tests/fixtures/binance_copy_login_required.json`
- Modify after observation: `docs/research/2026-08-09-exchange-private-trade-source-poc.md`

**Interfaces:**
- Produces: Binance 精确 host、path、method、request body、分页字段和响应字段映射
- Produces: `sourceRecordId` 稳定性结论
- Produces: 登录失效的可机器识别条件

- [ ] **Step 1: 由用户手动登录 Binance**

打开 Binance 官方网站并进入：

```text
https://www.binance.com/en/copy-trading/lead-details/5075281354358777856
```

用户在官方页面中手动完成登录。执行者不得要求用户粘贴密码、验证码、Cookie、token 或完整 HAR。

Expected: 页面明确显示熬鹰资本，并能进入用户所说的私域交易记录界面。

- [ ] **Step 2: 只记录候选请求元数据**

在开发者工具 Network 中清空旧请求，打开交易记录区域并翻到下一页。只记录以下元数据到临时目录：

```text
request URL（不含鉴权 query 值）
HTTP method
request body 中 Portfolio ID 与分页字段
response status
response Content-Type
```

Expected: 至少一个候选请求明确携带 `5075281354358777856`，且操作仅为读取交易记录。

- [ ] **Step 3: 验证响应字段和分页**

在本机临时目录检查候选 JSON，逐项对照页面至少 20 条记录；不足 20 条时核对全部：

```text
记录 ID
事件时间
交易对
开仓/加仓/减仓/平仓/反手语义
多空方向
数量
价格
杠杆
下一页游标或页码
```

Expected: 页面展示字段均能由响应直接解释；任何缺失字段写入研究结论，不能靠猜测补齐。

- [ ] **Step 4: 验证空结果与登录失效可区分**

在不清除用户主浏览器会话的情况下，用一个未登录的独立上下文访问同一只读请求，比较响应状态和业务错误码。

Expected: 未登录响应有稳定的状态码、错误码或结构特征，可映射为 `login_required`；它不能与“已登录且当前页无记录”的合法空结果相同。

- [ ] **Step 5: 生成 Binance 脱敏夹具**

从响应复制最少三类来源记录到 `collector/tests/fixtures/binance_copy_trade_records.json`：

```text
一条建立或增加方向敞口的记录
一条减少或关闭方向敞口的记录
一条分页边界附近的记录
```

保留真实字段名和类型，但把非目标用户标识替换为固定测试值；数量和价格改为保持运算关系的测试数值。`binance_copy_login_required.json` 只保存稳定错误结构，不保存响应 header。

- [ ] **Step 6: 扫描 Binance 夹具中的敏感信息**

Run:

```bash
! rg -ni 'cookie|authorization|bearer|csrf|token|email|phone|mobile|device|fingerprint|session|127\.0\.0\.1|192\.168\.' collector/tests/fixtures/binance_copy_*.json
```

Expected: 0 matches。若来源业务字段本身含上述普通词，必须人工确认其值不是鉴权或个人数据并在研究记录中说明。

---

### Task 3: 捕获 OKX App 交易记录只读契约

**Files:**
- Create on supported result: `collector/tests/fixtures/okx_orbit_trade_records.json`
- Create on supported result: `collector/tests/fixtures/okx_orbit_login_required.json`
- Modify after observation: `docs/research/2026-08-09-exchange-private-trade-source-poc.md`

**Interfaces:**
- Produces: OKX 精确 host、path、method、分页字段、鉴权依赖和响应字段映射
- Produces: `supported` 或 `unsupported` 结论

- [ ] **Step 1: 先尝试无需设备改动的观察方式**

用户在已登录的 OKX 官方 App 中打开十老板：

```text
Orbit User ID: 872838143249428480
页面动作: 个人资料 -> 交易记录
```

优先使用系统或现有工具已经提供的只读网络调试能力。不得为了 POC 擅自安装根证书、VPN profile、代理 App、越狱组件或关闭证书校验。

Expected: 若现有能力足够，进入下一步；若必须安装设备级组件，立即停止并向用户说明工具、证书范围、移除方式和风险，等待单独确认。

- [ ] **Step 2: 记录 OKX 候选请求元数据**

清空旧请求后只执行“打开交易记录、切换一次时间范围、加载下一页”三类读取动作。记录：

```text
request host/path/method
Orbit User ID 所在位置
游标或页码
响应 status/content-type
是否依赖每次变化的设备签名
```

Expected: 能把候选请求与十老板交易记录页面一一对应；不记录鉴权 header 的值。

- [ ] **Step 3: 核对字段完整性**

逐项对照至少 20 条 App 可见记录；不足 20 条时核对全部：

```text
稳定记录 ID
事件时间
合约/交易对
动作与方向
数量、成交或均价
杠杆
分页连续性
```

Expected: 响应可支持 `NormalizedTradeRecord`；如果只有收益截图、聚合指标或无数量快照，则不能宣称完整交易记录。

- [ ] **Step 4: 验证安全重放边界**

在不复制密码、验证码、Cookie 或 App 会话文件的条件下，验证同一只读请求是否能由受控本机 Collector 会话稳定发起。

Expected: 请求只依赖可由用户手动登录后建立的本机会话；若必须导出 App session、持久化设备签名材料或绕过证书固定，结论直接为 `unsupported`。

- [ ] **Step 5: 生成并扫描 OKX 脱敏夹具**

仅在 `supported` 时创建两个 JSON 夹具，保留来源字段名和类型，使用测试数量/价格并删除登录用户身份和鉴权材料。

Run:

```bash
! rg -ni 'cookie|authorization|bearer|csrf|token|email|phone|mobile|device|fingerprint|session|127\.0\.0\.1|192\.168\.' collector/tests/fixtures/okx_orbit_*.json
```

Expected: 0 matches。

---

### Task 4: 执行两次 10 分钟稳定性验证

**Files:**
- Modify: `docs/research/2026-08-09-exchange-private-trade-source-poc.md`

**Interfaces:**
- Consumes: 每个 supported 来源的候选只读请求
- Produces: ID、revision、排序和增量语义的稳定性证据

- [ ] **Step 1: 记录第一次观察**

对每个候选来源保存脱敏后的记录键列表：

```text
sourceRecordId
eventTime
semantic hash fields: symbol/action/side/quantity/price/leverage
page cursor
```

Expected: 列表按来源定义的稳定顺序保存，不包含行情浮动字段或未实现盈亏。

- [ ] **Step 2: 10 分钟后记录第二次观察**

使用产品要求的间隔等待下一次正常观察；不要高频轮询。重复完全相同的页面动作和分页范围。

Expected: 未变化记录的 ID 与语义字段相同；新增记录可以与旧记录明确分离；修订记录能通过相同 ID 加语义哈希变化识别。

- [ ] **Step 3: 判定 checkpoint 与 overlap 规则**

在研究记录中写明每个来源的固定规则：

```text
checkpoint = version + latest eventTime + sourceRecordId
overlap = 实测能覆盖延迟/修订的最小固定页数或记录数
ordering = ascending 或 descending
empty page = 合法空结果还是错误
```

Expected: 规则来自两次观察，不使用 markPrice、unrealizedProfit 等随行情变化字段作为 revision 输入。

---

### Task 5: 写出支持结论并提交脱敏证据

**Files:**
- Create: `docs/research/2026-08-09-exchange-private-trade-source-poc.md`
- Add only when supported: `collector/tests/fixtures/binance_copy_trade_records.json`
- Add only when supported: `collector/tests/fixtures/binance_copy_login_required.json`
- Add only when supported: `collector/tests/fixtures/okx_orbit_trade_records.json`
- Add only when supported: `collector/tests/fixtures/okx_orbit_login_required.json`

**Interfaces:**
- Produces: 每个来源的最终 `supported | unsupported` 状态
- Produces: 后续 provider 计划所需的确切字段映射，不包含待猜测项

- [ ] **Step 1: 写研究记录**

研究记录必须对每个来源逐项写出：

```text
status
target ID
exact read-only host/path/method
request pagination contract
response record schema
login_required signature
stable ID and revision rule
10-minute comparison result
security dependencies
known gaps
```

`unsupported` 必须附具体失败证据，例如“请求依赖不可安全持久化的设备签名”；不能只写“抓不到”。

- [ ] **Step 2: 验证没有提交临时捕获物**

Run:

```bash
git status --short
git diff --check
! git ls-files | rg -i '\.(har|pem|p12|pfx)$|cookie|profile|session'
```

Expected: 只出现研究 Markdown 和通过扫描的 JSON 夹具；未跟踪文件 `1` 仍未暂存。

- [ ] **Step 3: 根据结论执行硬门禁**

```text
Binance supported -> 可编写 binance_copy provider 实施计划
Binance unsupported -> 停止 Binance provider，向用户确认
OKX supported -> 可编写 okx_orbit provider 实施计划
OKX unsupported -> 停止 OKX provider，向用户确认，不启用公开快照
```

- [ ] **Step 4: 提交 POC 证据**

仅暂存实际生成且已脱敏的文件：

```bash
git add docs/research/2026-08-09-exchange-private-trade-source-poc.md collector/tests/fixtures/binance_copy_*.json collector/tests/fixtures/okx_orbit_*.json
git diff --cached --check
git commit -m "docs: record private trade source contracts"
```

若某一来源为 unsupported 且没有夹具，`git add` 中省略对应 glob，避免 shell 报错。

- [ ] **Step 5: 清理临时目录**

先把 Task 1 输出的绝对路径重新赋给 `POC_CAPTURE_DIR`，然后执行严格路径校验和单目录清理；下列 `find` 只作用于已经匹配的临时目录，不得把示例文本原样当作路径：

```bash
test -n "$POC_CAPTURE_DIR"
test -d "$POC_CAPTURE_DIR"
case "$POC_CAPTURE_DIR" in
  /var/folders/*/T/kol-trade-poc.*|/tmp/kol-trade-poc.*) ;;
  *) echo "Refusing unsafe capture path: $POC_CAPTURE_DIR" >&2; exit 1 ;;
esac
find "$POC_CAPTURE_DIR" -depth -mindepth 1 -delete
rmdir "$POC_CAPTURE_DIR"
```

Expected: 原始响应、临时请求元数据和任何浏览器调试文件不再留在磁盘；Git 中只保留脱敏证据。
