# Collector Launchd 与干净初始化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Collector 作为 macOS LaunchAgent 常驻，清理历史脏数据并为每个启用订阅仅初始化最新一条，同时补齐凭据与环境配置文档。

**Architecture:** launchd 负责进程生命周期，Collector scheduler 负责无 checkpoint 时的单条初始化，数据库清理由一次性、保留配置的脚本完成。根 `.env` 与 `collector/.env` 继续分离，ntfy server 固定为 `https://ntfy.sh`。

**Implementation notes:** 实际运行还验证并修复了两个环境边界：launchd 需固化安装时 PATH 才能找到 NVM OpenCLI；本地 agent 模式需关闭 API `STARTUP_BACKFILL_ENABLED`。ntfy 中文标题改用官方支持的 JSON 发布，避免 `httpx` 对非 ASCII Header 的编码错误。

**Tech Stack:** macOS launchd、Bash、Python 3.12+、SQLite、FastAPI/SQLAlchemy、MySQL、pytest。

## Global Constraints

- 不使用 subagent，不创建 worktree，不暂存或提交用户当前未跟踪基线。
- 保留两个启用订阅现有的 `custom-v1` system/user prompt、model config 与 ntfy topic。
- 历史内容清理是破坏性操作，只删除内容/运行历史，不删除 KOL、订阅、通知规则或模型配置。
- 所有 secret 只存在被忽略的 env 文件，任何验证输出只显示 `SET/UNSET` 或长度。

---

### Task 1: 无 checkpoint 时只初始化最新一条

**Files:**
- Modify: `collector/collector_agent/config.py`
- Modify: `collector/collector_agent/scheduler.py`
- Modify: `collector/collector_agent/main.py`
- Modify: `collector/.env.example`
- Test: `collector/tests/test_scheduler.py`

**Interfaces:**
- Consumes: `CollectorStore.checkpoint_for(subscription_id) -> str | None`
- Produces: `CollectorScheduler(..., initial_fetch_limit: int = 1)`；已有 checkpoint 时 fetch limit 为 50，无 checkpoint 时为配置值。

- [x] 在 scheduler 测试中记录 provider 收到的 limit，并断言首次为 1、存在 checkpoint 后为 50。
- [x] 运行 `python -m pytest -q tests/test_scheduler.py`，确认新断言因当前固定 50 而失败。
- [x] 增加 `INITIAL_FETCH_LIMIT` 配置并传入 scheduler，做最小条件选择。
- [x] 再次运行 scheduler 测试，确认通过。

### Task 2: LaunchAgent 生命周期

**Files:**
- Create: `scripts/collector-launchd-run.sh`
- Create: `scripts/collector-launchd-install.sh`
- Create: `scripts/collector-launchd-uninstall.sh`
- Create: `scripts/com.caoyifan.kol-crawler.collector.plist.template`
- Create: `scripts/tests/test-collector-launchd.sh`
- Modify: `scripts/collector-start.sh`
- Modify: `scripts/collector-stop.sh`
- Modify: `scripts/collector-status.sh`

**Interfaces:**
- Produces: LaunchAgent label `com.caoyifan.kol-crawler.collector`；安装脚本支持 `COLLECTOR_LAUNCH_AGENTS_DIR` 与 `LAUNCHCTL_BIN` 测试覆盖。

- [x] 用临时 HOME 和 fake launchctl 编写安装/卸载测试，断言 plist 路径、绝对项目路径、`RunAtLoad`、`KeepAlive` 与 bootstrap/bootout 调用。
- [x] 运行 `bash scripts/tests/test-collector-launchd.sh`，确认因脚本不存在而失败。
- [x] 实现最小 plist 模板、前台 runner、安装与卸载脚本；让 start/stop/status 优先操作 launchd，未安装时保留兼容路径。
- [x] 运行 Shell 测试与 `bash -n scripts/*.sh scripts/tests/*.sh`，确认通过。
- [x] 在本机执行安装脚本，并以 `launchctl print`、status、日志和新鲜 heartbeat 验证。

### Task 3: 清理历史并干净初始化

**Files:**
- Create: `scripts/reset-signal-history.sh`
- Create: `backend/tests/test_history_reset.py`
- Create: `backend/app/services/history_reset.py`

**Interfaces:**
- Produces: `reset_signal_history(session: Session) -> dict[str, int]`，返回各删除表计数并重置订阅采集状态。

- [x] 写后端测试：准备 KOL、订阅、自定义提示词、通知规则、RawPost/Signal/Asset 关系和 heartbeat；清理后内容表与派生 Asset 为空且配置对象字段不变。
- [x] 运行目标测试，确认服务函数不存在而失败。
- [x] 实现事务内按外键顺序清理和订阅状态重置，Shell 脚本负责先停 launchd、调用容器内服务、删除本地 SQLite、再启动 launchd。
- [x] 运行目标测试和后端完整测试，确认通过。
- [x] 执行一次真实清理；等待两个启用订阅各生成最新 1 条并验证模型状态。

### Task 4: 精简 ntfy 信号消息

**Files:**
- Modify: `backend/app/services/notifications.py`
- Modify: `backend/tests/test_notifications.py`

**Interfaces:**
- Produces: `_format_notification(...) -> tuple[str, str]`，标题和正文只使用中文摘要、标的、方向。

- [x] 修改通知测试，精确断言正文为摘要/标的/方向三行，并断言标题/正文不含 KOL、要点或来源。
- [x] 运行 `pytest -q tests/test_notifications.py`，确认旧格式导致失败。
- [x] 删除旧通知格式中的 KOL、要点和来源，只保留三个指定字段。
- [x] 再次运行通知测试与后端完整测试，确认通过。

### Task 5: ntfy、账号密码和 env 文档

**Files:**
- Modify: `.env.example`
- Modify: `collector/.env.example`
- Modify: `docs/configuration.md`
- Modify: `docs/operations.md`
- Modify: `README.md`
- Modify: `docs/verification.md`

**Interfaces:**
- Documents: launchd 安装/状态/重启/卸载；bcrypt 密码修改；JWT、collector token/hash、encryption key 等生成方式。

- [x] 将根 `.env` 与 `collector/.env` 的 ntfy server 设置为 `https://ntfy.sh`，topic 使用数据库现有值且不输出明文。
- [x] 在配置文档中区分“必须生成”“按服务提供”“本地默认即可”三类变量，并给出不把密码写进 shell history 的修改流程。
- [x] 在运维文档加入 launchd 全生命周期、历史重置命令和验收命令。
- [x] 更新验收记录，写入实际测试数量、初始化后的数据计数、provider 状态与已知限制。
- [x] 运行 Compose 校验、Python 编译、Shell 语法、后端/Collector 测试和前端构建。
