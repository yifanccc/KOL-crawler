# Verification

执行日期：2026-07-13 至 2026-07-14。验收使用当前本机私有配置；本文件不记录任何明文密码、API key、hash、ntfy topic 或 token。

## 自动化验证

后端在项目 Python 3.12 API 镜像内执行，宿主 Python 3.13 未安装 `bcrypt`/`python-jose`，不作为项目运行环境：

```bash
docker compose run --rm --no-deps \
  -e DEEPSEEK_API_KEY= \
  -e OPENAI_API_KEY= \
  -v "$PWD/backend/app:/app/app:ro" \
  -v "$PWD/backend/tests:/app/tests:ro" \
  api sh -lc 'pip install --no-cache-dir pytest pytest-mock respx && pytest -q'
```

结果：54 passed，1 条 Starlette TestClient 弃用警告。

```bash
(cd collector && python -m pytest -q)
(cd frontend && node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --experimental-strip-types --test tests/refreshPolicy.test.mjs)
(cd frontend && npm run build)
docker compose config --quiet
python -m compileall -q backend/app collector/collector_agent
bash -n scripts/*.sh scripts/tests/*.sh
bash scripts/tests/test-collector-launchd.sh
```

结果：Collector 19 passed；前端刷新策略 3 passed；LaunchAgent 安装/卸载测试通过；Next.js 15.5.20 生产构建成功，生成 `/`、`/login`、`/admin`、`/kols`、`/assets` 等 8 个路由；Compose 配置、Python 编译与 Shell 语法检查成功。新增后端并发测试的 RED 延迟为 0.2016 秒，使用工作线程后的 GREEN 延迟为 0.0105 秒。

`npm audit --omit=dev`：2 moderate，0 high，0 critical。没有在本任务中做破坏性依赖升级。

## Docker 与认证

```bash
docker compose up --build -d
docker compose ps
curl -fsS http://localhost:8010/health
```

MySQL、Redis、API、Web 均启动；本地验收地址为 Web `http://localhost:3010`、API `http://localhost:8010`。HTTP 结果：login 200、session 200、signals 200、logout 200、logout 后 signals 401。管理员 Cookie 不能调用 Collector API，Collector Bearer token 不能调用 Dashboard API，该边界同时由后端测试覆盖。

## OpenCLI 与本地 Collector

```bash
opencli twitter --help
opencli twitter tweets aleabitoreddit --limit 1 --format json
./scripts/collector-launchd-install.sh
./scripts/collector-status.sh
./scripts/collector-logs.sh --lines 20
./scripts/collector-stop.sh
```

OpenCLI v1.8.5 的 `tweets` 命令成功返回真实 JSON；Provider 解析结果为 1 条、`authenticated`，正确识别 handle、显示名和 UTC 时间。真实 LaunchAgent `com.caoyifan.kol-crawler.collector` 已安装到当前用户，`RunAtLoad`/`KeepAlive` 生效，status 为 `running <pid> (launchd)`；plist 中的 PATH 包含 NVM OpenCLI 目录。

真实一轮 Collector 联动更新 heartbeat，服务端结果为 agent `home-mac-01`、overall `healthy`、X `authenticated`、Binance `healthy`、Outbox 0。网络失败、上传退避、provider 隔离、登录失败不推进 checkpoint、冷却与恢复告警由 Collector 测试覆盖。

### 历史清理与单条初始化

执行 `./scripts/reset-signal-history.sh --yes` 前，清理计数为 RawPost 70、Signal 70、SignalAsset 142、SignalTag 31、Asset 64、CrawlRun 603、CollectorAgent 1；KOL、Subscription、NotificationRule、ModelConfig 和自定义提示词不在删除范围。

关闭 API 旧回填（`STARTUP_BACKFILL_ENABLED=false`）并修正 launchd PATH 后，真实干净初始化结果为：2 个启用订阅、RawPost 2、Signal 2；X `aleabitoreddit` 与 Binance `btc7873` 各 1 条 RawPost 和 1 条 Signal，两个 Signal 的 `structured_status` 均为 `ok`。两个订阅仍为 `custom-v1`，system/user prompt 长度分别保持 436/40。

ntfy server 已配置为 `https://ntfy.sh`，私有 topic 未写入输出。初始化过程中产生 1 条自然命中规则的 NotificationEvent，状态为 `sent` 且无错误。信号正文由测试精确锁定为中文摘要、标的、方向三行；Collector 与 API 均改用 ntfy JSON 发布，中文标题不再进入 HTTP Header。

2026-07-13 追加验证：标题调整为 `平台 | KOL昵称 | 原帖北京时间`。测试覆盖 X 平台映射、UTC 到 `Asia/Shanghai` 转换、昵称优先，以及昵称缺失时显示 `未知 KOL` 且绝不回退账号 handle；正文三行保持不变。

## 端到端数据

后端 `test_collector_e2e.py` 覆盖英文 X、中文、Binance、无标的和畸形模型五类 fixture。重复上传验证为 5 个 RawPost、5 个 Signal，SignalAsset/SignalTag/NotificationEvent 均不重复；无标的结果安全完成，畸形模型使用中文 fallback。

Docker 栈另上传 `qa-btc-spx-20260711`，结果从 `accepted` 进入 `completed`，Signal 保存 `BTC`/`SPX`，资产关系为 BTC/CRYPTO 与 SPX/US_STOCK。Dashboard 顶部 BTC 搜索提交后从 11 items 过滤到 1 item；点击同卡片 SPX 徽章后仍为 1 item，搜索值同步为 SPX。

## 浏览器 QA

真实浏览器验证了：未登录访问受保护路由跳转 `/login?next=%2F`；登录后 Dashboard 加载；Admin 显示订阅、有效 prompt/schema 与 Collector provider 状态；KOL 页面显示采集器状态；logout 后 API 返回 401；页面控制台无 error/warning。

| 视口 | scrollWidth/clientWidth | 横向溢出 | 主栏/侧栏重叠面积 | 可交互控件 | 零尺寸控件 | 结果 |
|---|---:|---|---:|---:|---:|---|
| 1440×900 | 1440/1440 | 否 | 0 | 111 | 0 | 通过 |
| 1280×800 | 1280/1280 | 否 | 0 | 111 | 0 | 通过 |
| 390×844 | 390/390 | 否 | 0 | 111 | 0 | 通过；无不可滚动的裁切控件 |

浏览器验收过程中修复了两个真实缺陷：顶部搜索增加明确、可访问的提交按钮；Collector heartbeat 无时区值统一按 UTC 输出 `Z`，避免上海时区 UI 错显为 8 小时前。

### 交互样式一致性回归

对 `/`、`/kols`、`/assets`、`/kols/1`、`/assets/BTC`、`/admin` 逐页扫描按钮、输入框、选择框和文本域。修复前，右上角退出按钮以及 Admin 的新建订阅、订阅列表、配置输入框、prompt 编辑器和保存按钮仍使用浏览器原生样式；登录页的新表单类也没有对应样式。

修复后，上述控件统一使用现有 Graphite/Cyan 颜色、`6px` 低圆角、细边框与既有 primary/ghost 层级。1440×900、1024×768、390×844 三档运行时扫描均为：原生样式控件 0、横向溢出 0。顶部搜索输入 `nvda` 并点击提交后，搜索值与标的筛选同步为 `NVDA`，情报流收敛为 7 items；控制台 error/warning 为 0。

本轮已恢复应用内浏览器截图验证，并确认 Dashboard 顶部搜索、Admin 设置页、Collector 状态、订阅列表、表单与市场选择控件的视觉层级一致。

## `www.yifanlab.cloud/kol` 生产验收

2026-07-13 将独立生产 Compose 部署到 `/home/deploy/kol-crawler`。Web/API 分别只监听 `127.0.0.1:13010` 与 `127.0.0.1:18010`；MySQL、Redis 没有宿主机发布端口。Nginx 只在现有 `yifanlab.cloud` server 中 include `/etc/nginx/snippets/kol-crawler.conf`，安装前备份为：

```text
/etc/nginx/sites-available/yifanlab.cloud.before-kol-20260713174834
```

安装脚本的 `nginx -t` 与 reload 成功。公网烟测结果：

| 地址 | 结果 |
|---|---|
| `http://www.yifanlab.cloud/` | 200，原站点保持可用 |
| `http://www.yifanlab.cloud/vibe-trading/` | 200，原子路径保持可用 |
| `http://www.yifanlab.cloud/kol` | 307 到 `/kol/login?next=%2F` |
| `http://www.yifanlab.cloud/kol/login` | 200 |
| `/kol/_next/static/...js` | 200 |
| 未认证 `/kol/api/signals` | 401 |
| 携带现有 Collector token 的 `/kol/api/v1/collector/config` | 200，7 个未删除订阅且 agent ID 匹配 |

API 日志记录了成功登录 200，随后 signals/kols/assets 均为 200；本轮自动化浏览器连接在导航阶段超时，因此没有把 curl/API 日志替代为 DOM、截图或控制台结论。后续证书上线后应重新做一次隔离浏览器 QA。

本地 Collector 已切换到 `PUBLIC_API_URL=http://www.yifanlab.cloud/kol`。真实 restart 后，远端 heartbeat 从 `2026-07-13 09:55:22` 推进到 `09:57:27`（服务器时间），overall `healthy`、Outbox 0；provider 为 X `authenticated`、Binance Square `healthy`。切换时暴露并修复了 launchd teardown 竞态：`collector-stop.sh` 现在等待 job 确认卸载，模拟测试已锁定立即 `stop → start` 的行为。

生产验收后重新执行：后端 54 passed（1 条既有 Starlette 弃用警告）、Collector 22 passed、前端刷新策略 3 passed、launchd 脚本测试通过、生产部署契约通过、`NEXT_PUBLIC_BASE_PATH=/kol` 的 Next.js 生产构建通过。

### 10 分钟调度与非阻断刷新回归

2026-07-14 追加生产验收：

- `GET /api/admin/config-options` 返回 `defaultIntervalMinutes=10`，默认 System/User prompt 与 2026-07-13 Serenity 固定快照一致。
- 生产 7 个未删除订阅的 `intervalMinutes` 均为 10；只更新了调度间隔，没有修改 checkpoint、历史帖子、信号或各订阅现有提示词。
- 本机 `collector/.env` 为 `CONFIG_POLL_SECONDS=600`，launchd 状态为 running。重启后的首轮在 `2026-07-13T15:51:51Z` 完成，下一轮在 `2026-07-13T16:04:11Z` 开始，两轮 7 个订阅均为 `status=success fetched=0`。Collector 是“每轮执行完再等待 600 秒”，因此两轮日志时间差还包含上一轮约 2 分钟的实际抓取耗时，不是整点 cron。
- 远端 heartbeat 为 `healthy`，X 为 `authenticated`、Binance Square 为 `healthy`、Outbox 为 0。
- 页面不可用有两层根因：首页和共享数据 Hook 每 60 秒刷新时重新设置全屏 Loading；API 分析循环又在事件循环内同步调用模型。现在仅首次加载阻断，后续刷新失败保留最后一次成功内容；分析批次通过工作线程执行，模型请求期间 API 仍可响应。60 秒读取周期不变。
- 更新后的 Web/API 已在服务器通过 production Compose 在线构建并分别重建；MySQL、Redis 和 Nginx 未重启。根站点返回 200，`/kol` 未登录时 307 到登录页，登录页 200。
- 独立浏览器会话没有管理员登录态，因此本轮浏览器烟测覆盖未认证跳转和登录页：文档加载完成、无横向溢出、控制台无 error/warning。认证后的 60 秒刷新行为由 3 个刷新策略测试、TypeScript/Next.js production build 和生产 API 连续 200 日志共同验证；后续人工已登录浏览器可按运维文档再观察一轮。
- 第三轮 Collector 在 `2026-07-13T16:16:39Z` 抓到 1 条新帖；旧 API 的 heartbeat 随后 `ConnectTimeout`，但本地 Outbox 为 0，远端 RawPost 139 已完成并生成 Signal 82，数据没有丢失。发布并发修复后，`2026-07-13T16:29:31Z` 下一轮 7 个订阅全部成功，heartbeat 更新到 `2026-07-13T16:29:32Z`。
- 生产 `OPENAI_MODEL` 于北京时间 2026-07-14 00:32 快速切换为 `gpt-5.6-terra`，配置备份为 `.env.before-openai-model-20260714003213`。该操作未 build 镜像，只强制重建 API；容器内 `get_settings().openai_model`、健康检查和最小严格 JSON Schema Responses 请求均验证通过。

### 双模型协议回归

每次修改模型客户端或部署配置后执行：

```bash
cd backend
python -m pytest -q tests/test_config.py tests/test_structurer.py
```

回归必须覆盖：默认使用 DeepSeek `chat_completions`，同时继续接受 `responses`/`chat_completions`；官方 DeepSeek 地址只选用 `DEEPSEEK_API_KEY`，其他兼容地址继续选用并保留 `OPENAI_API_KEY`；Responses 模式继续发送严格 JSON Schema；Chat Completions 模式请求 `/chat/completions`、发送 `response_format={"type":"json_object"}` 并把 Schema 放入 System prompt；客户端返回内容仍通过统一的 Pydantic 结构校验和 fallback 边界。真实 API key 不进入自动化测试或仓库，生产切换后另按部署文档执行容器内烟测。

2026-07-15 本地实现验收：模型配置与客户端定向测试 `19 passed`；依赖完整的隔离 API 容器中后端全量测试 `59 passed`（1 条既有 Starlette 弃用警告）；Python 编译、开发/生产 Compose 配置解析及生产部署契约均通过。本次没有使用或写入 DeepSeek key，也没有切换生产模型。

### Collector 停机补抓上限

2026-07-14 将已有 checkpoint 后的增量抓取从硬编码 50 改为可配置 `CATCHUP_FETCH_LIMIT=5`。测试覆盖默认值 5、环境变量覆盖与最小值 1、进程重启后复用 SQLite checkpoint、Scheduler 使用首次 1/补抓 5，以及 X 上游超额返回时只保留最新 5 条。Binance Square 原有实现已经在 provider 边界执行相同的最近 limit 条截断。

补抓批次按旧到新原子写入 Outbox 并推进到最新 checkpoint；若 checkpoint 后超过 5 条，更老的超额部分按用户确认的方案 A 永久跳过。上传失败仍由现有 Outbox 退避重试保障，不会重复依赖 provider 补抓。

本机 `collector/.env` 写入 `CATCHUP_FETCH_LIMIT=5` 后真实重启 launchd Collector。北京时间 2026-07-14 23:19:19 的首轮 7 个订阅全部 `status=success`、失败 0，本地 Outbox 0；远端 heartbeat 同步更新，overall healthy、X authenticated、Binance Square healthy。

### 真实总数、执行性筛选与分页

2026-07-20 排查确认生产数据库有 124 条 Signal，但旧 `GET /api/signals` 只返回默认窗口中的 100 个 `items`，且不返回总数元数据；首页因此把 `signals.length` 错当成“总样本数”。修复后接口新增向后兼容的 `total`、`overallTotal`、`actionableTotal`、`limit`、`offset`，并把 KOL、平台、方向、执行性、标的、标签、时间、重要性过滤全部移到数据库分页之前。排序继续使用原帖 `published_at DESC, Signal.id DESC`。

自动化验收结果：

- API 镜像内后端全量测试 63 passed，1 条既有 Starlette TestClient 弃用警告；新增用例覆盖 105 条分页、旧窗口之外的可执行信号、平台/24 小时/重要性组合过滤和非法分页边界。
- 前端 Node 测试 6 passed，TypeScript `--noEmit` 通过，Next.js 15.5.20 生产构建成功；首页路由首包 6.29 kB。
- Collector 变更前的全量测试 22 passed；Compose 本地/生产配置、生产部署契约、Python 编译、Shell 语法与 `git diff --check` 均通过。

本地真实浏览器验证了筛选栏“全部 / 仅可执行”和“可执行”统计卡双向同步：启用后 `aria-pressed=true`、列表从 2 条收敛为 1 条，点击统计卡可恢复全部结果。桌面 1280 px 和移动端 390 px 均无横向溢出、溢出控件为 0，控制台 error/warning 为 0；新增控件继续使用 Graphite/Cyan 面板、绿色可执行语义和既有低圆角。

生产只同步本次 8 个运行时代码文件，发布前备份位于：

```text
/home/deploy/kol-crawler/.runtime/deploy-backups/signal-total-filter-20260720225618
```

API/Web 通过 `deploy/docker-compose.prod.yml` 在线构建，API 依赖明确使用腾讯云 PyPI 镜像；只强制重建 `api`、`web`，MySQL、Redis、Nginx、`.env` 和本机 Collector 均未重启。生产认证烟测结果：

| 检查 | 结果 |
|---|---|
| 首批 `items` / `total` / `overallTotal` | 100 / 124 / 124 |
| `offset=100` 第二页 | 24 条 |
| `actionableTotal` | 32 |
| `actionable=true` | 返回 32 条且全部 `actionable=true` |
| `limit=101` | 422 |
| 合并两页 `publishedAt` | 全部 124 条保持倒序 |
| 公网 `/kol/api/signals` | 200，`overallTotal=124` |
| 公网认证首页 | 200，包含“执行性 / 上一页 / 下一页”新 UI |
| 根站点、`/vibe-trading/`、`/kol/login` | 均为 200 |
| 未登录 `/kol` | 307 到 `/kol/login?next=%2F` |
| API/Web 最近日志 | 无 ERROR、Traceback、Exception |

### Collector provider 失败日志语义

同日发布后健康核对暴露出旧日志语义缺陷：OpenCLI 超时时，X provider 会返回空列表并把自身健康状态设为 `failed`；Scheduler 过去只按“没有抛异常”写成 `status=success fetched=0`。先增加复现测试确认 RED，再在写 checkpoint 前检查 provider 健康状态；`failed`/`login_required` 现在写为 `status=failed error=ProviderHealth provider_status=<状态>`，不写 checkpoint、不加入成功列表，最终 Collector 全量测试为 23 passed。

重启本机 launchd 后，北京时间 2026-07-20 23:02 开始的真实一轮准确区分了成功与失败：5 个订阅成功，Binance `btc7873` 和 X `Jukanlosreve` 各 1 个订阅失败；旧实现会把这两条都误记为成功。该轮 Outbox 为 0，没有丢失待上传数据。

继续按相同输入对比运行环境后确认了两类独立问题：

- Binance 在普通进程约 15 秒成功，但在 macOS `taskpolicy -b` 下稳定于约 2 分钟后失败；launchd 模板原有 `ProcessType=Background` 与该行为一致。删除该键、保留 `RunAtLoad`/`KeepAlive` 后，真实 launchd 中 Binance 恢复 `status=success fetched=0`。
- 当前终端的 OpenCLI 使用代理环境，而旧 plist 只固化 PATH；`TJ_Research` 在终端约 30 秒成功，在缺少代理的 launchd 中会 60 秒超时。安装脚本现在把安装时已有的 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、`NO_PROXY` 经过 XML 转义写入权限为 600 的 plist，测试使用假代理值验证，真实验收只检查键存在、不输出值。

北京时间 2026-07-20 23:28 的最终真实轮次中，Binance 与 5 个有效 X 订阅成功；`Jukanlosreve` 仍失败，独立 OpenCLI 命令明确返回 `Could not resolve @Jukanlosreve`，属于该订阅账号不可解析，未自动删除或推进 checkpoint。最终远端 heartbeat 为 overall `healthy`、Binance `healthy`、X `authenticated`、Outbox 0，launchd 进程持续运行。

### Binance Copy 成交监控本地验收

2026-08-12 在专属分支完成 Binance-only 本地验收，目标为熬鹰资本 Portfolio ID `5075281354358777856`；OKX 未注册 provider，也未进入运行范围。

- Collector 全量 `50 passed`。四轮合成回归覆盖首轮基线无 Outbox、第二轮新增成交生成一条事件、第三轮重复保持幂等、第四轮访问失效保留 checkpoint 且仓位转为 `STALE`；重叠窗口缺口另有测试锁定为 `UNKNOWN`。
- 隔离 API 容器后端全量 `88 passed`，只有 1 条既有 Starlette/httpx 弃用警告。端到端上传确认交易 payload 绕过 LLM，生成 `structuredStatus=deterministic` 的 private Signal 和一条 ntfy 事件；常规 `/api/signals` 为 0 条，管理端 `/api/admin/signals` 返回该事件。
- 前端 Node 测试 `12 passed`，TypeScript `--noEmit` 和 Next.js 生产构建通过，构建包含 `/admin/signals`。Node 只报告既有的 package module type 提示。
- 使用隔离 SQLite API、临时 Chrome profile 和本地开发 Web 验证 `/admin/signals`：接口 200、控制台 error 0、失败响应 0；1440×1000 与 320×900 均无横向溢出，筛选在移动端收敛为单列，标题/空状态/焦点顺序和可访问名称正常。临时 profile、脚本和截图已移到废纸篓，没有复用用户打开的 Binance 会话。
- 对固定 Binance host/path 执行一次无状态只读实源烟测，结果为 provider `healthy`、返回 100 条、生成 checkpoint、`history_complete=false`，记录 ID 与 revision 均为 64 位哈希；命令未打印成交字段，也未读取或保存 Cookie/Authorization。
- 生产构建在隔离端口验证：未登录 `GET /icon.svg` 返回 200，未登录 `GET /admin/signals` 仍返回 307 并跳转 `/login?next=%2Fadmin%2Fsignals`。

本验收只证明代码、合成数据和已验证只读响应契约在本机可用，不代表已部署到生产。当前 Binance 首屏请求不发送或保存 Cookie/Authorization；应用仍将生成的数据强制标为 `private`。

### Binance Copy 仓位变动批量通知本地验收

2026-08-23 将 Binance Copy 的 ntfy 粒度从“每笔成交一条”改为“每次订阅采集一条”。逐笔 RawPost、Signal 和操作记录继续保留；Collector 为同批新成交生成稳定 batch ID、批次总数和按品种/方向计算的仓位前后差异。后端等待该批全部 Signal 就绪后，以第一条 Signal 作为唯一通知锚点，只在方向、数量、推测开仓均价或杠杆确有变化时发送。mark price、预计盈亏和账户保证金的单独刷新不产生交易 Outbox。

- 隔离 API 容器后端全量 `96 passed`，仅 1 条既有 Starlette/httpx 弃用警告；测试覆盖两笔成交等待并合成一条通知、仓位 `0.10 → 0.18`、成交数量/均价/金额汇总、重复调度幂等，以及空 `positionChanges` 零推送。
- Collector 全量 `57 passed`；测试覆盖同批两笔事件共享 batch ID/size、聚合前后仓位、无仓位变化的交易修订，以及仅 mark price 从 50,000 更新到 51,000 时 Outbox 仍为 0。
- 本地 API 已重新构建并重启，`GET /health` 为 200；MySQL 已存在 `notification_batch_id`、`notification_batch_size` 和组合索引。launchd Collector 已于北京时间 20:19 重启并加载当前分支代码，本地待上传 Outbox 和死信均为 0。
- 本轮没有伪造真实成交，也没有向用户的真实 ntfy topic 发送测试通知；首次真实汇总推送需等待 Binance 后续出现实际仓位变动。

### Binance Copy 仓位监控生产部署

2026-08-24 将专属分支 `codex/okx-binance-trade-monitor-design` 的 API、Web 与数据库迁移部署到 `/home/deploy/kol-crawler`。发布前完整备份位于：

```text
/home/deploy/kol-crawler/.runtime/deploy-backups/binance-position-batch-20260824223523
```

发布只重建并替换 API、Web；MySQL、Redis、Nginx 和生产 `.env` 未重启或改写。同步时发现文档中的根目录 `rsync --delete` 会删除服务器独有备份，因此本次改用不删除远端文件的受限同步，并排除 `.env*`、`backups/`、`.runtime/`、`.git/` 与构建缓存。生产 `.env` 的 SHA256 在同步前后保持一致。

- API `/health` 返回 200；HTTPS 公网 `/kol/login` 返回 200，未登录 `/kol/positions` 返回 307 到 HTTPS 登录页，未认证 `/kol/api/position-kols` 返回 401。API/Web 最近日志无启动异常。
- MySQL 已存在 `raw_posts.notification_batch_id`、`notification_batch_size` 与 `ix_raw_posts_subscription_notification_batch` 索引。
- 生产新增且仅新增一个 Binance Copy 私域订阅：熬鹰资本、Portfolio ID `5075281354358777856`、10 分钟、无 prompt；订阅级 ntfy 规则沿用生产默认 server/topic，已启用且配置完整。
- 重启本机 launchd Collector 后，首轮真实读取返回 100 条成交并以 `baseline_created` 完成；生产已收到 13 条仓位状态、100 条操作记录和账户保证金快照。当前 1 条仓位可完整估算，4 条历史窗口不足的仓位保持 `UNKNOWN`，KOL 汇总明确标为 `PARTIAL`，没有把未知数量或成本补成 0。
- 生产 heartbeat 为 `healthy`，provider 状态为 Binance Copy `healthy`、Binance Square `healthy`、X `authenticated`，Outbox 为 0。首次基线没有生成 RawPost、Signal 或 NotificationEvent，也没有发送人工 ntfy 测试；后续只有真实仓位结构变化才会按单轮采集合并推送。
- 容器内 OpenAI-compatible 实请求使用 `deepseek-v4-flash` 与 `chat_completions` 成功返回合法结构，HTTP/HTTPS proxy 均已注入，`used_fallback=false`。
- 部署后磁盘剩余约 2.8 GB（使用率 93%）；未执行全局 Docker prune，以免删除其他项目缓存或本次回滚镜像。Web 构建仍报告 4 个 high severity npm 依赖项，本次没有做超出范围的破坏性升级。
- 首次 HTTPS 人工登录暴露出生产 Web build arg 仍为 HTTP：浏览器在发送登录请求前按混合内容拦截，页面显示 `Failed to fetch`。修复后仅重建 Web，生产 bundle 包含 `https://www.yifanlab.cloud/kol` 且不再包含对应 HTTP 地址；HTTPS 登录页 200，畸形登录 POST 通过同一路由到达 API 并返回预期 422。API、数据库和 Collector 未重启，修复前 Compose 备份位于 `.runtime/deploy-backups/https-login-20260824225241`。

### Binance Copy 空仓起算时间生产部署

2026-08-25 为 Binance Copy 订阅增加可配置的空仓起算时间，并将熬鹰资本订阅 ID 17 设置为北京时间 `2026-08-19 00:00`，即 UTC `2026-08-18T16:00:00Z`。发布前停止本机 Collector；线上源代码和数据库备份位于 `/home/deploy/kol-crawler/.runtime/deploy-backups/position-start-20260825195827`，本机 SQLite 备份位于 `.runtime/deploy-backups/position-start-20260825195827/collector.sqlite3`。

- 后端全量 `98 passed`，Collector 全量 `64 passed`，前端 Node `25 passed`；TypeScript `--noEmit` 与 Next.js 生产构建通过。测试覆盖起算前拒绝、修改起算点双端清账、空首轮基线、首笔后续交易通知以及超过 100 条时拒绝不完整重建。
- 生产只重建并替换 API、Web；MySQL、Redis、Nginx 和 `.env` 未改写或重启。迁移新增 `subscriptions.position_start_at`，HTTPS 登录页返回 200，未登录持仓页仍 307 到登录页，新设置文案存在于生产静态 bundle。
- 修改配置前线上有 14 条仓位状态、106 条操作和 1 条账户快照。配置更新通过管理 API 完成，服务端先清空这三类推算数据；本地 Collector 随后清空旧的 106 笔账本，以 `baseline_created fetched=47` 静默重建。重建后的首笔操作时间为 UTC `2026-08-19 06:47:01`，没有起算点之前的数据。
- 当时账本含 47 条操作、11 条仓位状态，其中 7 条已平仓、2 条可推算的活跃空仓、2 条 `UNKNOWN`。BTCUSDT 与 XAUUSDT 空仓可正常推算；ASTERUSDT 和 NEIROUSDT 的首笔都是开多，但起算后累计平多币数分别超过累计开多币数 42,101 ASTER 和 284,298,174 NEIRO，旧规则因此将最终状态降为 `UNKNOWN`，KOL 汇总保持 `PARTIAL`。
- 重建前后该订阅 RawPost 与 Signal 均保持 6 条；重建后新增 NotificationEvent 为 0。本地 Outbox 和死信均为 0，生产 heartbeat 为 `healthy`，Binance Copy/Binance Square 为 `healthy`、X 为 `authenticated`。
- 生产磁盘剩余约 3.4 GB（使用率 92%），未运行全局 Docker prune。

### Binance Copy 数量账本与手机推送生产部署

2026-08-25 将显式空仓基线后的仓位运算固定为成交币数账本：开仓按 `executedQty` 增加，平仓按 `executedQty` 减少并最多扣到 0，成交金额不参与仓位数量。未设置空仓起算时间的订阅仍保留矛盾记录转 `UNKNOWN` 的保护。ntfy 同批成交改为按“开/平、空/多、币种”合并，平仓汇总 `totalPnl`，随后列出 KOL 的全部当前仓位。

- 后端全量 `99 passed`，Collector 全量 `65 passed`；真实 47 笔本机账本离线重放后，ASTERUSDT 与 NEIROUSDT 均为 `FLAT / 0 / HIGH`。测试同时锁定无显式空仓基线时超额平仓仍为 `UNKNOWN`、操作快照使用相同基线语义、手机推送精确排版、两笔平仓的数量加权价格和已实现盈亏汇总。
- 发布提交为 `b52c3d3`。发布前停止本机 Collector；本机 SQLite 备份位于 `.runtime/deploy-backups/quantity-ledger-20260825213434/collector.sqlite3`，线上数据库和源码备份位于 `/home/deploy/kol-crawler/.runtime/deploy-backups/quantity-ledger-20260825213434`。
- 线上只重建并替换 API，Web、MySQL、Redis 与 Nginx 未重启；生产 `.env` 的 SHA-256 与发布前备份一致。API 健康检查和 HTTPS 登录页返回 200，未登录持仓页返回 307 到登录页。
- 重启本机 Collector 后，本轮 Binance Copy 成功读取 47 条并上传仓位。生产现有 11 条仓位状态为 2 条 `ACTIVE`、9 条 `FLAT`、0 条 `UNKNOWN`；ASTERUSDT 与 NEIROUSDT 均为 `FLAT / 0 / HIGH`。对应操作仍保留原始成交币数，ASTERUSDT 最后一笔和 NEIROUSDT 平仓均为 `CLOSE`，没有生成反向空仓。
- 生产仍有 47 条操作、6 条 RawPost、6 条 Signal；本机 Outbox 与死信均为 0，没有为历史基线生成新推送。Collector 心跳为 `healthy` 且 Outbox 为 0，Binance Copy/Binance Square 为 `healthy`、X 为 `authenticated`。
- 容器内用真实 BTCUSDT、XAUUSDT 当前仓位只读渲染新消息：数量、均价、标记价、预计盈亏、按建仓名义金额计算的盈亏比例，以及按账户保证金余额计算的仓位倍数均有值。没有向真实 ntfy topic 发送测试通知；首次真实成交推送仍由下一次仓位变动触发。
- 发布后生产磁盘剩余约 3.0 GB（使用率 93%），未运行全局 Docker prune。

### Binance Copy ntfy 失败重试生产修复

2026-08-26 排查熬鹰资本最新 MSTRUSDT 成交未推送：交易、RawPost 和 Signal 都已正常入库，唯一通知事件 228 在首次发送时收到 `429 Too Many Requests`。旧逻辑虽然保留了 `failed` 事件，但后续调度会因 `(signal_id, notification_rule_id)` 唯一约束直接跳过，因此一次临时限流会永久漏推；同一轮排查还发现此前批次事件 227 因相同 429 未送达。

- 通知事件新增 `attempt_count` 和 `next_attempt_at`，失败后在同一事件上按服务端 `Retry-After` 或 60 秒起的指数退避继续尝试，最多 8 次；`sent` 事件仍不会重复发送。分析循环即使没有待处理 RawPost 也会处理到期重试，旧失败事件没有显式排期时不会被批量回放。
- 生产 API 容器直连 `ntfy.sh` 的 TLS 握手超时，经现有容器代理访问返回 200，因此最终实现保留代理环境，没有把 ntfy 加入 `NO_PROXY`。
- 发布前数据库、源码和 `.env` 校验值备份位于 `/home/deploy/kol-crawler/.runtime/deploy-backups/ntfy-retry-20260826214142`。生产只重建并替换 API；Web、MySQL、Redis、Nginx 和 `.env` 未改写或重启。
- 只为已核实的事件 227、228 写入一次到期时间。两条事件均在新机制第一次回放后于 UTC `2026-08-26 13:48:45` 变为 `sent`，`attempt_count=1`、`next_attempt_at=NULL`、错误信息清空；Signal 1255 和 1261 合计仍只有 2 条 NotificationEvent，没有产生重复记录。
- 最新操作仍为 PositionOperation 160：MSTRUSDT、开空增仓、数量 `2129.79000000`、成交价 `126.80105640`、UTC `2026-08-25 19:33:37`；其 RawPost 1360、Signal 1261 和 NotificationEvent 228 关联一致。
- 最终后端全量 `102 passed`，Collector 全量 `65 passed`，前端 Node `25 passed`；TypeScript、Next.js 生产构建、生产部署契约和 `git diff --check` 均通过。API `/health` 与 HTTPS 登录页返回 200，生产磁盘剩余约 3.5 GB（使用率 91%）。

### Binance Copy 一分钟监测生产部署

2026-08-31 将 Binance Copy 订阅的固定监测间隔从 10 分钟改为 1 分钟；普通 X 和 Binance Square 订阅仍保持 10 分钟。新增订阅默认使用 1 分钟，管理端不再接受 Binance Copy 的其他间隔，API 启动迁移也会将已有 Binance Copy 订阅统一修正为 1 分钟。

- 最终后端全量 `102 passed`，Collector 全量 `65 passed`，前端 Node `25 passed`；TypeScript `--noEmit`、Next.js 生产构建、生产部署契约与 `git diff --check` 均通过。发布提交为 `362b794`。
- 发布前停止本机 Collector；本机 SQLite 与配置备份位于 `.runtime/deploy-backups/binance-copy-one-minute-20260831080419`，线上数据库、源码与 `.env` 校验值备份位于 `/home/deploy/kol-crawler/.runtime/deploy-backups/binance-copy-one-minute-20260831080419`。
- 线上只重建并替换 API、Web；MySQL、Redis、Nginx 未重启，生产 `.env` 校验值未变化。API `/health` 和 HTTPS `/kol/login` 返回 200，生产静态 bundle 包含“标记价格约每分钟更新”。
- 生产现有三条 Binance Copy 订阅均已启用且为 1 分钟：熬鹰资本 ID 17、重生 ID 18、意钦 ID 19。三者的 Portfolio ID、起算时间、账本、仓位和历史记录均未修改。
- 本机 Collector 的 `CONFIG_POLL_SECONDS=60`。重启后的完整轮次为 UTC `00:08:46.222`、`00:11:55.474`、`00:12:57.528`、`00:13:59.591`；首轮还要执行全部到期的普通订阅，后续稳定两次相邻间隔分别约 62.05 秒和 62.06 秒。实际间隔为 60 秒等待加本轮约 2 秒请求耗时，并非整点 cron。
- 三个稳定轮次中，熬鹰资本每轮成功读取 69 条、重生 43 条、意钦 11 条；普通订阅均正确显示 `not_due`。生产每轮三个仓位上传及 heartbeat 全部返回 200，本机 Outbox 和死信均为 0，launchd Collector 持续运行。

### Binance Copy 恢复十分钟监测生产部署

2026-09-04 将 Binance Copy 的固定监测间隔从 1 分钟恢复为 10 分钟。后端默认值、已有订阅迁移、管理端约束、Collector 主循环和持仓详情文案同步恢复，普通订阅仍保持原有 10 分钟配置。功能提交为 `89e5bf1`。

- 最终后端全量 `102 passed`，Collector 全量 `65 passed`，前端 Node `25 passed`；TypeScript `--noEmit`、Next.js 生产构建、生产部署契约、Python 编译、Shell 语法与 `git diff --check` 均通过。后端测试在与生产一致的新 API 镜像中执行，只有 2 条既有 Starlette/anyio 弃用警告。
- 发布前停止本机 Collector。本机 SQLite 与配置备份位于 `.runtime/deploy-backups/binance-copy-ten-minute-20260904212006`，线上数据库、源码和 `.env` 校验值备份位于 `/home/deploy/kol-crawler/.runtime/deploy-backups/binance-copy-ten-minute-20260904212006`；SQLite integrity check、数据库 gzip 和源码 tar 均已验证。旧运行镜像在新构建后已无本地引用，无法额外创建镜像标签，回滚仍可使用上述源码与数据库备份。
- 线上只重建并替换 API、Web；MySQL、Redis 持续运行且健康，Nginx 未重启，生产 `.env` 校验值未变化。API 容器 `/health` 返回 200，HTTPS `/kol/login` 返回 200，生产静态 bundle 包含“标记价格每 10 分钟更新”，API/Web 近 30 分钟日志无 ERROR、Traceback、Exception 或 Unhandled。
- 生产三条 Binance Copy 订阅均已启用且恢复为 10 分钟：熬鹰资本 ID 17、重生 ID 18、意钦 ID 19。Portfolio ID、空仓起算时间、账本、仓位和历史记录均未修改。
- 本机 `collector/.env` 已恢复为 `CONFIG_POLL_SECONDS=600`，运行时读取值也是 600。launchd Collector 重启后的首轮从 UTC `2026-09-04T13:26:32.939193Z` 开始，熬鹰资本、重生、意钦分别成功读取 90、75、97 条；生产对应三次仓位上传和 heartbeat 均返回 200。
- 首轮完成后继续观察 75 秒，没有出现旧的一分钟轮次，launchd 进程持续运行；本地 Outbox 和死信均为 0。Collector 仍采用“本轮完成后等待 600 秒”的调度模型，因此实际相邻轮次间隔为 10 分钟加本轮执行耗时，不是整点 cron。X 订阅 `Jukanlosreve` 的既有 ProviderHealth 失败保持原状，与本次 Binance 间隔变更无关。

## 外部前置条件

- ntfy server/topic 已配置；本轮没有额外制造测试信号，初始化信号自然触发的 1 条通知已发送成功。消息格式、UTF-8 JSON 发布、require-asset 和 exactly-once 均由后端/Collector 测试覆盖。
- X 首次登录必须在采集机人工执行；本次机器登录态有效并已完成真实读取。
- 前端生产依赖仍有 2 个 moderate npm audit 项，升级前应逐项审阅 changelog 与锁文件变化。
- 2026-08-24 已验证 HTTPS `/kol/login` 返回 200、持仓页登录跳转与 API 认证边界正常；HTTP 入口仍可直接访问而非强制跳转，使用时应固定访问 HTTPS，后续可单独配置全站 HTTP 到 HTTPS 重定向。
