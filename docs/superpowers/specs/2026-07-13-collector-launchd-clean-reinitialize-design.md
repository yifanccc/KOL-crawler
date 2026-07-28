# Collector Launchd 与干净初始化设计

## 状态

已确认，2026-07-13。

## 目标

将本机 Collector 安装为当前 macOS 用户的 LaunchAgent，登录后自动运行并在异常退出时自动拉起；删除历史采集和信号脏数据后，每个启用订阅只抓最新一条作为新基线；保留 KOL、订阅、用户修改的 `custom-v1` 提示词、模型配置和 ntfy topic。

## 设计

- LaunchAgent label 固定为 `com.caoyifan.kol-crawler.collector`，plist 安装到 `~/Library/LaunchAgents/`。
- launchd 直接以前台方式运行 `python -u -m collector_agent`；`RunAtLoad` 与 `KeepAlive` 均启用，stdout/stderr 写入项目 `.runtime/collector.log`。
- 安装、卸载、启动、停止、状态检查通过仓库 `scripts/` 完成，不依赖易失的 `nohup` 子进程。
- plist 固化安装时的 `PATH`，确保 launchd 的最小环境也能找到 NVM 安装的 OpenCLI；Python/OpenCLI 路径变化后重新运行安装脚本。
- Collector 在订阅没有本地 checkpoint 时只取最新 `INITIAL_FETCH_LIMIT=1` 条；建立 checkpoint 后恢复每轮最多 50 条增量抓取。
- 本地 Collector 模式关闭 API 的 `STARTUP_BACKFILL_ENABLED`，避免容器启动回填与本地 agent 争用 checkpoint 或重复抓取。
- 清理时删除 RawPost、Signal、SignalAsset、SignalTag、由信号派生的 Asset、NotificationEvent、CrawlRun 和旧 Collector heartbeat；重置订阅 checkpoint/时间字段并删除本地 SQLite。KOL、Subscription、NotificationRule、ModelConfig 均保留。
- ntfy server 使用 `https://ntfy.sh`；现有订阅 topic 原样保留并同步给本机 provider 告警。
- ntfy 信号推送只包含中文摘要、标的和方向判断；标题与正文均不得加入 KOL、要点、来源、风险提示或原文。
- ntfy 使用 JSON 发布中文标题和正文，不把非 ASCII 文本放入 HTTP Header。

## 安全约束

- `.env` 与 `collector/.env` 不进入 Git，不在日志或文档中记录真实 token、topic、密码 hash 或 API key。
- 修改管理员密码时只把 bcrypt hash 写入根 `.env`，不保存明文密码；修改后必须重建 API/Web，旧登录 Cookie 随 JWT 配置不变但账号密码立即按新 hash 验证。
- 清理前先停止 Collector；清理后验证两个启用订阅的提示词长度、版本和 ntfy topic 与清理前一致。

## 验收标准

- `launchctl print gui/$UID/com.caoyifan.kol-crawler.collector` 成功，Collector heartbeat 新鲜。
- X 与 Binance 两个启用订阅各有 1 条新 RawPost 和 1 条 Signal，均使用 `structured_status=ok`。
- 数据库无旧 RawPost/Signal，订阅仍为 `custom-v1`，ntfy server/topic 可用。
- ntfy 消息正文严格为 `摘要`、`标的`、`方向` 三行。
- 文档包含 launchd 安装/重启/卸载、账号密码修改、必须生成与可选 env 的准确命令。

## 实施结果

2026-07-13 验收完成：LaunchAgent 正常运行，X 为 `authenticated`、Binance 为 `healthy`；两个启用订阅各保留最新 1 条 RawPost 和 1 条 Signal，两个 Signal 均为 `structured_status=ok`，自定义 `custom-v1` 提示词保持不变。
