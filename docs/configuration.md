# Configuration

项目使用两份互不替代的配置：根目录 `.env` 供 Docker 中的 API/Web 使用，`collector/.env` 仅供本机采集进程使用。两边唯一需要配对的是 `COLLECTOR_AGENT_ID` 和 collector token。

## 管理员账号和密码

管理员没有注册页面，账号由根 `.env` 的 `ADMIN_USERNAME` 和 `ADMIN_PASSWORD_HASH` 决定。密码只保存 bcrypt hash；用交互式输入生成 hash，避免把明文写进 shell history：

```bash
python - <<'PY'
import getpass
import bcrypt

password = getpass.getpass("新管理员密码：")
confirm = getpass.getpass("再次输入：")
if password != confirm:
    raise SystemExit("两次密码不一致")
if len(password.encode("utf-8")) > 72:
    raise SystemExit("bcrypt 密码不能超过 72 个 UTF-8 字节")
print(bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode())
PY
```

把输出写入 `ADMIN_PASSWORD_HASH`，同时按需修改 `ADMIN_USERNAME`，然后只重建 API 进程：

```bash
docker compose up -d --force-recreate --no-deps api
curl -fsS http://localhost:8010/health
```

修改用户名会让旧 Cookie 因 subject 不匹配而失效；只修改密码不会主动注销已经签发的 Cookie。若需要强制所有会话退出，同时重新生成 `JWT_SECRET`。

## 需要生成的凭据

根目录 `.env` 仅保留在部署主机。必须自行生成或替换示例值的项目如下：

| 配置 | 如何取得 |
|---|---|
| `ADMIN_PASSWORD_HASH` | 使用上面的交互式 bcrypt 命令 |
| `JWT_SECRET` | `python -c 'import secrets; print(secrets.token_urlsafe(48))'` |
| `COLLECTOR_TOKEN` / `COLLECTOR_TOKEN_HASH` | 使用下面的成对生成命令；明文只写入 `collector/.env` |
| `MYSQL_ROOT_PASSWORD` / `MYSQL_PASSWORD` | 生产或可被其他机器访问时分别生成高熵随机值 |
| `NTFY_TOPIC` | 使用不可猜测的私有 topic；当前已配置时不要重新生成 |

`ENCRYPTION_KEY` 当前由 API 读取，但现有实现尚未用它加密数据库字段；仍应替换 `change-me` 占位值并妥善保管。可用与 `JWT_SECRET` 相同的命令生成，后续启用字段加密后不能随意轮换。

推荐一次生成 collector 明文 token 与对应 hash，输出第一行写入 `collector/.env`，第二行写入根 `.env`：

```bash
python - <<'PY'
import hashlib
import secrets

token = secrets.token_urlsafe(48)
print(f"COLLECTOR_TOKEN={token}")
print(f"COLLECTOR_TOKEN_HASH={hashlib.sha256(token.encode()).hexdigest()}")
PY
```

ntfy topic 需要新建时可生成一个符合 ntfy 命名规则的随机值：

```bash
python -c 'import secrets; print("kol-" + secrets.token_hex(20))'
```

`DEEPSEEK_API_KEY`、`OPENAI_API_KEY` 和可选的 `NTFY_TOKEN` 不是本地生成：前两者分别由 DeepSeek 与 OpenAI/其他兼容服务商提供，后者仅在 ntfy 服务启用鉴权时由 ntfy 服务提供。两把模型 Key 可以同时保留在 `.env`；官方 DeepSeek Base URL 使用 `DEEPSEEK_API_KEY`，其他 Base URL 使用 `OPENAI_API_KEY`，切换模型不会覆盖另一把 Key。`MODEL_API_STYLE`、`OPENAI_BASE_URL`、`OPENAI_MODEL`、端口、URL、轮询周期和浏览器路径是部署参数，不属于 secret。

## 公网服务

从 `.env.example` 复制后，至少填写：

| 配置 | 作用 |
|---|---|
| `ADMIN_USERNAME` / `ADMIN_PASSWORD_HASH` | 管理后台账号和 bcrypt 密码 hash |
| `JWT_SECRET` | 至少 32 字符的登录签名 secret |
| `AUTH_COOKIE_NAME` | API 与 Web 必须一致 |
| `COOKIE_SECURE` | 本地 HTTP 为 `false`；公网 HTTPS 为 `true` |
| `WEB_ORIGIN` | Web 的完整源，例如 `http://localhost:3010`，不能是 `*` |
| `COLLECTOR_AGENT_ID` | 本机采集器标识，必须与 `collector/.env` 一致 |
| `COLLECTOR_TOKEN_HASH` | `collector/.env` 中明文 token 的 SHA-256 |
| `MODEL_API_STYLE` / `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` | 中文结构化观点模型、独立服务商 Key 及其 API 协议 |
| `PUBLIC_API_BASE_URL` | 浏览器访问 API 的地址，例如 `http://localhost:8010` |

本地 Collector 模式必须保持 `ENABLE_SCHEDULER=false` 和 `STARTUP_BACKFILL_ENABLED=false`，否则 API 会与本地 Collector 重复抓取，清理 checkpoint 后还可能在容器启动阶段执行旧回填。

`COLLECTOR_TOKEN_HASH` 是 Collector 明文 token 的 SHA-256；明文仅存在 `collector/.env`。`ANALYSIS_POLL_SECONDS` 控制公网 pending 分析循环；`ENABLE_SCHEDULER=false` 是本地 agent 模式的安全默认值。

模型通过 `MODEL_API_STYLE`、`DEEPSEEK_API_KEY`、`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`、`MODEL_REASONING_EFFORT` 和 `MODEL_TIMEOUT_SECONDS` 配置。默认值为 DeepSeek 官方 Chat Completions；`MODEL_API_STYLE=chat_completions` 请求 `{base_url}/chat/completions`，启用 JSON Object 模式，并把同一份 JSON Schema 写入 System prompt 后继续执行本地 Pydantic 校验。原有 `MODEL_API_STYLE=responses` 继续受支持，请求 `{base_url}/v1/responses` 并使用严格 JSON Schema。

DeepSeek 直连配置如下；`deepseek-v4-pro` 适合优先保证摘要质量，`MODEL_REASONING_EFFORT=high` 与[官方 Chat Completions 文档](https://api-docs.deepseek.com/zh-cn/api/create-chat-completion/)一致：

```dotenv
MODEL_API_STYLE=chat_completions
DEEPSEEK_API_KEY=<DeepSeek API key>
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-v4-pro
MODEL_REASONING_EFFORT=high
MODEL_TIMEOUT_SECONDS=180
```

切回现有 Responses 服务时，只需恢复 `MODEL_API_STYLE`、base URL 和模型名；原有 `OPENAI_API_KEY` 会继续保留并自动启用。API 容器启动时当前服务商没有 key，或模型请求、返回格式校验失败，就会生成“模型暂时不可用；原文涉及……”这类启发式 fallback。只修改上述运行时模型参数时无需重新 build 镜像，但必须强制重建 API 容器，容器不会自动读取新值：

```bash
docker compose up -d --force-recreate --no-deps api
```

只有代码或 Python 依赖改变时才需要先执行 `docker compose build api`。容器重建只影响之后进入分析队列的帖子；已经生成 fallback Signal 的历史帖子不会自动重复调用模型。公网信号通知使用 `NTFY_SERVER`、私有 `NTFY_TOPIC` 和可选 `NTFY_TOKEN`；真实 topic/token 不写入示例或文档。

## 本地 Collector

从 `collector/.env.example` 创建 `collector/.env`：

- `PUBLIC_API_URL`：公网 API 根地址，不包含 `/api/v1/collector`。
- `COLLECTOR_AGENT_ID`：必须与公网配置一致。
- `COLLECTOR_TOKEN`：明文高熵 token，只存在采集机。
- `COLLECTOR_DB_PATH`：SQLite Outbox 路径，默认放在 `.runtime/`。
- `CONFIG_POLL_SECONDS`：配置与调度循环间隔，默认 `600` 秒（10 分钟）。
- `INITIAL_FETCH_LIMIT`：本地 checkpoint 不存在时的初始化条数，默认 `1`。
- `CATCHUP_FETCH_LIMIT`：已有 checkpoint 时的补抓上限，默认 `5`；不足 5 条时全部补抓，超过时只保留最新 5 条。
- `NTFY_SERVER`、`NTFY_TOPIC`、`NTFY_TOKEN`：本机 provider 健康告警。
- `PROVIDER_ALERT_COOLDOWN_SECONDS`：重复故障告警冷却，默认 300 秒。
- `BINANCE_BROWSER_EXECUTABLE`：本机 Chrome/Chromium 路径；macOS Chrome 默认可填 `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`。
- `BINANCE_SQUARE_LANG`：Binance Square 页面语言，默认 `zh-CN`。

Binance 订阅填写个人主页最后一段 slug，例如 `https://www.binance.com/zh-CN/square/profile/btc7873` 应填写 `btc7873`，不能填写展示名、纯数字用户 ID 或整条 URL。Binance 没有公开的他人帖子读取 API，collector 会在本机启动无头 Chrome，获取网页请求所需的指纹头后读取用户资料和帖子；因此 Binance 采集要求本机安装 Chrome/Chromium。

上段只适用于 `binance_square`。Binance Copy 交易订阅在 Admin 中选择 `Binance Copy`，填写展示名和固定数字 Portfolio ID；熬鹰资本使用 `5075281354358777856`。服务端会自动强制：

- `platform=binance_copy`
- `visibility=private`
- `intervalMinutes=10`
- `accountId` 为 8 至 32 位数字，创建后不可修改，并按平台与 ID 唯一
- 通知最低置信度默认为“低”；普通 KOL 订阅仍默认为“中”

Binance Copy provider 当前不需要额外环境变量、Chrome 会话或 Binance 登录凭据。它只读最近 100 条成交记录，并把 checkpoint、交易 ledger、推测仓位和待上传 Outbox 保存在 `COLLECTOR_DB_PATH` 指向的本机 SQLite。首轮仅建立基线；模型 Key、System prompt 和 User prompt 不参与交易数值解析。若内部 BAPI 后续增加访问门槛，应先让 provider health 降级并重新验证只读会话边界，不能把 Cookie 或 Authorization 写进 `.env`、数据库、日志或 Git。

删除订阅是软删除：该平台/handle 不再出现在订阅和 KOL 列表，也不会继续下发给 collector，但已经保存的原帖和历史信号仍保留。

Collector 停机后重启时会复用本机 SQLite checkpoint。X 与 Binance Square 都按 checkpoint 过滤，只把最近最多 `CATCHUP_FETCH_LIMIT` 条按旧到新写入 Outbox，并把 checkpoint 推进到本批最新帖子。超过上限的更老帖子会永久跳过；上传网络失败时帖子保留在 Outbox，不会因 checkpoint 已推进而丢失。修改该配置后需要重启 Collector。

新增订阅的抓取间隔默认是 10 分钟。Admin 表单与创建 API 使用同一默认值；当前默认 System prompt、User prompt 和 Output Schema 是 2026-07-13 Serenity（`aleabitoreddit`）配置的固定快照。以后单独修改 Serenity 不会自动改变新增订阅默认值。

交易订阅固定为 10 分钟；API 和 Admin 都拒绝其它间隔。实际抓取时间为该订阅上轮开始时间加 10 分钟，并受 `CONFIG_POLL_SECONDS` 调度循环粒度影响，不承诺严格整点。

## 哪些值本地可以不改

- `AUTH_COOKIE_NAME`、`ACCESS_TOKEN_EXPIRE_MINUTES`、轮询/超时参数可保留默认值。
- `COOKIE_SECURE=false` 仅适用于本地 HTTP；HTTPS 部署必须改为 `true`。
- `COLLECTOR_AGENT_ID` 不必随机，但根 `.env` 与 `collector/.env` 必须完全一致。
- `NTFY_TOKEN` 在 `ntfy.sh` 私有随机 topic 且未开启账号鉴权时可留空；topic 本身应视作密码。
- 根 `.env` 中旧的 `SECRET_KEY`、`NEXT_PUBLIC_API_BASE_URL` 不被当前后端配置读取；前端实际使用 `PUBLIC_API_BASE_URL` 通过 Compose 构建参数注入。
