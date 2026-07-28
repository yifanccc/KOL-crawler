# Operations

## Collector

首次在 macOS 当前用户下安装 launchd：

```bash
./scripts/collector-launchd-install.sh
launchctl print gui/$(id -u)/com.caoyifan.kol-crawler.collector
./scripts/collector-status.sh
```

安装脚本会把当前 Python 路径和当前 `PATH` 固化到 plist，使 launchd 能找到 NVM 安装的 `opencli`。如果安装命令所在终端配置了 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、`NO_PROXY`，脚本也会把已有值经过 XML 转义后写入权限为 `600` 的 plist，供 OpenCLI 在 launchd 最小环境中使用；安装过程和日志不会输出代理值。代理、Python、Node/OpenCLI 路径变化或项目移动后，都要重新执行安装脚本。

plist 不得设置 `ProcessType=Background`。真实验证表明该策略会过度降权 Playwright/Chrome：相同 Binance 请求在普通进程约 15 秒成功，在后台策略下约 2 分钟后失败。Collector 仍由 `RunAtLoad`、`KeepAlive` 和自身 10 分钟循环控制，不需要用 `ProcessType` 才能常驻。

日常管理：

```bash
./scripts/collector-start.sh
./scripts/collector-status.sh
./scripts/collector-logs.sh --lines 100
./scripts/collector-stop.sh
./scripts/collector-launchd-uninstall.sh
```

Collector 每轮检查都会按订阅向 `.runtime/collector.log` 写一条结构化日志，状态固定为：

- `status=success fetched=<数量>`：provider 返回 `healthy`/`authenticated`，且本次抓取及本地 checkpoint/Outbox 写入成功；健康抓取但没有新帖时才会写 `fetched=0`。
- `status=skipped reason=<原因>`：本轮未执行抓取，常见原因为 `not_due`、`disabled`、`active` 或 `provider_missing`。
- `status=failed error=<异常类型>`：provider 抛出异常或本地保存失败。
- `status=failed error=ProviderHealth provider_status=<状态>`：provider 没有抛出异常，但主动报告 `failed`/`login_required`；OpenCLI 超时、Binance 请求失败等返回空列表的故障也属于失败，不能记作 `success fetched=0`，且不会推进 checkpoint。

日志同时包含 UTC 时间、订阅 ID、平台和 handle，可直接筛选：

```bash
./scripts/collector-logs.sh --lines 100
rg 'status=(success|skipped|failed)' .runtime/collector.log
```

Collector 配置循环和所有正常订阅的默认抓取间隔均为 10 分钟（`CONFIG_POLL_SECONDS=600`、`intervalMinutes=10`）。Dashboard 仍每 60 秒读取一次已完成数据，但后台刷新不会清空当前页面或显示全屏 Loading；抓取和页面刷新是两个独立周期。

首次没有 checkpoint 时只初始化最新 `INITIAL_FETCH_LIMIT=1` 条；Collector 停机后恢复时，已有 checkpoint 的订阅补抓最近最多 `CATCHUP_FETCH_LIMIT=5` 条。少于 5 条会全部补齐，超过 5 条时更老的超额帖子会跳过。帖子与新 checkpoint 在同一 SQLite 事务中写入，之后即使公网上传失败，也会留在 Outbox 中继续重试。

Collector 上传新帖后，API 会在工作线程中执行同步模型分析，FastAPI 事件循环继续响应 Dashboard。若新帖已保存但 heartbeat 出现 `ConnectTimeout`，先检查远端 RawPost/Signal 和本地 Outbox；Outbox 为 0 且远端 Signal 已生成表示数据没有丢失，后续 heartbeat 会在下一轮恢复。

安装 launchd 后，`start`/`stop` 只装载或卸载服务但保留 plist，登录后仍可自动启动；`uninstall` 才会卸载并删除 plist。未安装 launchd 时脚本保留原来的 PID/nohup 兼容路径。

`collector-stop.sh` 会等待 launchd 完成卸载（最多 5 秒）后才返回，避免紧接着执行 `collector-start.sh` 时因旧 job 仍在 teardown 而收到 launchctl 退出码 37。

只有同时满足以下条件才算真正调通：

1. `./scripts/collector-status.sh` 输出 `running <pid>`；
2. `.runtime/collector.log` 没有缺少 `PUBLIC_API_URL`、`COLLECTOR_AGENT_ID`、`COLLECTOR_TOKEN` 或浏览器启动错误；
3. Admin 的 Collector 心跳时间在约两个 `CONFIG_POLL_SECONDS`（默认 20 分钟）内，并且目标 provider 为 `healthy`/`authenticated`。

Dashboard 展示的是“最后一次 heartbeat”，历史记录为 healthy 不代表当前进程仍在运行。`collector/.env` 不存在或 token 与公网 hash 不匹配时，collector 无法正常启动。

### 在本地 API 与公网 API 之间切换

Nginx 路由上线并验证后，把 `collector/.env` 中唯一一行改为：

```dotenv
PUBLIC_API_URL=http://www.yifanlab.cloud/kol
```

然后重启并检查日志与新鲜 heartbeat：

```bash
./scripts/collector-stop.sh
./scripts/collector-start.sh
./scripts/collector-status.sh
./scripts/collector-logs.sh --lines 100
```

如果公网入口异常，回滚为 `PUBLIC_API_URL=http://localhost:8010` 后再次重启。切换 API 不清空本地 Outbox；网络失败的 pending 原帖会在目标恢复后继续重试。当前公网入口为 HTTP，Collector token 会以明文经过公网；证书完成后必须同步改为 `https://www.yifanlab.cloud/kol`。

Outbox 网络失败时保持 `pending`，上传重试按 2、4、8 秒增长并封顶 300 秒；服务端 `accepted` 或 `duplicate` 才删除，`invalid` 转入 SQLite `dead_letters`。检查数据库前先停止进程：

```bash
sqlite3 .runtime/collector.sqlite3 'select id, subscription_id, external_id, status from outbox_posts;'
sqlite3 .runtime/collector.sqlite3 'select id, external_id, reason, created_at from dead_letters;'
```

X 显示 `login_required` 时运行 `opencli twitter login`，恢复后无需清空 checkpoint。X 显示 `failed` 且 message 为 `OpenCLI timed out` 时，先确认 plist 是否包含当前终端使用的代理键，再从逐订阅日志确认具体失败 handle；同轮其他 handle 可能继续成功。OpenCLI 明确返回 `Could not resolve @<handle>` 时属于账号名称无效或账号不可解析，应在 Admin 核对该订阅，不能靠增加超时解决，也不要自动推进 checkpoint。单个 provider 的失败不影响其他 provider；故障和恢复通知受 `PROVIDER_ALERT_COOLDOWN_SECONDS` 控制。

Binance 显示 `failed` 时先确认 handle 是个人主页 slug，再确认 `BINANCE_BROWSER_EXECUTABLE` 指向可执行的 Chrome/Chromium。Binance 首次抓取会启动浏览器并等待页面产生请求指纹，通常比 X 抓取更慢。

### 清空历史并重新初始化

以下命令是破坏性操作：删除所有原帖、信号、派生资产、通知事件、抓取运行记录和旧 heartbeat，重置 checkpoint，并删除本机 Outbox SQLite。它会保留 KOL、订阅、模型配置、通知规则和用户修改的提示词，然后重启 Collector，让每个启用订阅只抓最新 1 条：

```bash
./scripts/reset-signal-history.sh --yes
```

执行后按顺序验收：

```bash
./scripts/collector-status.sh
./scripts/collector-logs.sh --lines 100
launchctl print gui/$(id -u)/com.caoyifan.kol-crawler.collector
```

Admin 中应看到新鲜 heartbeat；X 为 `authenticated`、Binance 为 `healthy`；每个启用订阅各有 1 条 RawPost 和 1 条 Signal。模型分析可能需要数十秒，期间原帖会先出现，Signal 稍后生成。

## 数据库与恢复

启动 API 会执行幂等 Python 迁移；手工 MySQL 迁移在 `backend/migrations/`。升级前备份：`mysqldump --single-transaction -u kol_app -p kol_signal > backup.sql`；恢复前停止 API，再执行 `mysql -u kol_app -p kol_signal < backup.sql`。应用回滚时部署上一镜像，但保留 nullable/default 新列；不要为回滚删除生产列或原始帖子。

## 健康检查

```bash
docker compose ps
docker compose logs -f api
curl -fsS http://localhost:8000/health
```

线上隔离 Compose 的检查命令：

```bash
ssh deploy@www.yifanlab.cloud
cd /home/deploy/kol-crawler
docker compose --env-file .env -f deploy/docker-compose.prod.yml ps
curl -fsS http://127.0.0.1:18010/health
curl -fsS -o /dev/null http://127.0.0.1:13010/kol/login
docker compose --env-file .env -f deploy/docker-compose.prod.yml logs --tail=100 api web
```

Dashboard 的 Collector 状态来自最近一次 heartbeat；心跳陈旧时先检查本机进程、OpenCLI 登录、Binance 浏览器和公网连通性。管理员登录限速是单进程有界缓存，多 API 副本部署需改为共享限速器。

## 通知排查

信号通知以 `(signal_id, notification_rule_id)` 唯一，重试不会再次 publish。真实 ntfy topic/token 只放在 `.env`；用部署方明确授权的测试规则发送一条通知并记录 HTTP 状态，日志中不得输出 token。provider 健康通知由本机 Collector 发送，与公网信号通知相互独立。

信号标题固定为 `平台 | KOL昵称 | 原帖北京时间`，例如 `X | Serenity | 2026-07-13 08:45`。昵称只读取原帖 `author_name`，绝不使用账号 handle；昵称缺失时显示 `未知 KOL`。原帖时间转换为 `Asia/Shanghai` 并显示到分钟，缺失时显示 `时间未知`。

信号推送正文严格只有三行：

```text
摘要：<中文摘要>
标的：<标的列表或无>
方向：<方向判断>
```

中文标题和正文使用 ntfy JSON 发布，避免把非 ASCII 文本放入 HTTP Header。
