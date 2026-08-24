# Deployment

## `www.yifanlab.cloud/kol` 部署

该站点使用独立 Compose 项目 `kol-crawler`：Web 仅监听 `127.0.0.1:13010`，API 仅监听 `127.0.0.1:18010`，MySQL 与 Redis 不发布宿主机端口。Next.js 以真实 `basePath=/kol` 构建；Nginx 必须使用 `^~ /kol/`，否则站点已有的静态资源正则可能截获 `/_next` 文件。

服务器目录固定为 `/home/deploy/kol-crawler`。同步代码时不能覆盖服务器 `.env`：

```bash
rsync -az \
  --exclude='.git/' --exclude='.DS_Store' --exclude='.env*' \
  --exclude='backups/' --exclude='node_modules/' --exclude='.next/' \
  --exclude='.runtime/' \
  ./ deploy@www.yifanlab.cloud:/home/deploy/kol-crawler/
```

首次部署把当前根 `.env` 单独复制到服务器并限制权限。当前约定沿用现有账号、模型、ntfy 与 collector 密钥，不把明文密码写进仓库：

```bash
scp .env deploy@www.yifanlab.cloud:/home/deploy/kol-crawler/.env
ssh deploy@www.yifanlab.cloud 'chmod 600 /home/deploy/kol-crawler/.env'
```

生产 Compose 会强制使用以下部署参数，不需要改动本机 `.env`：

- `WEB_ORIGIN=http://www.yifanlab.cloud`
- `PUBLIC_API_BASE_URL=https://www.yifanlab.cloud/kol`
- `NEXT_PUBLIC_BASE_PATH=/kol`
- `COOKIE_SECURE=false`
- `ENABLE_SCHEDULER=false`
- `STARTUP_BACKFILL_ENABLED=false`

构建与启动：

```bash
ssh deploy@www.yifanlab.cloud
cd /home/deploy/kol-crawler
docker compose --env-file .env -f deploy/docker-compose.prod.yml config --quiet
bash scripts/tests/test-production-deployment.sh
docker compose --env-file .env -f deploy/docker-compose.prod.yml build api web
docker compose --env-file .env -f deploy/docker-compose.prod.yml up -d
docker compose --env-file .env -f deploy/docker-compose.prod.yml ps
curl -fsS http://127.0.0.1:18010/health
curl -fsS -o /dev/null http://127.0.0.1:13010/kol/login
```

生产 Compose 默认通过腾讯云 PyPI 镜像在线构建 API，避免服务器直连 `pypi.org` / `files.pythonhosted.org` 超时。需要切换包源时，在服务器 `.env` 设置 `PIP_INDEX_URL` 后重新执行 Compose build：

```bash
PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple
docker compose --env-file .env -f deploy/docker-compose.prod.yml build api
```

### 切换模型服务

首次部署包含 `MODEL_API_STYLE` 的双协议代码时，需要同步代码并重新 build API 镜像。镜像已经包含该功能后，只修改协议、模型地址、模型名或 key 不需要重新 build。先备份生产 `.env`：

```bash
cd /home/deploy/kol-crawler
cp -p .env ".env.before-openai-model-$(date +%Y%m%d%H%M%S)"
# 编辑 .env 中的模型配置；不要在终端或文档中输出 API key
```

DeepSeek 官方 API 使用以下配置：

```dotenv
MODEL_API_STYLE=chat_completions
DEEPSEEK_API_KEY=<DeepSeek API key>
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-v4-pro
MODEL_REASONING_EFFORT=high
MODEL_TIMEOUT_SECONDS=180
```

第一次发布本次代码执行在线 build；腾讯云服务器继续使用生产 Compose 中的腾讯云 PyPI 镜像：

```bash
docker compose --env-file .env -f deploy/docker-compose.prod.yml build api
docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  up -d --no-deps api
```

以后只切换已经支持的模型配置时，跳过 build，只强制重建 API 容器：

```bash
docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  up -d --no-deps --force-recreate api
docker compose --env-file .env -f deploy/docker-compose.prod.yml \
  exec -T api python -c 'from app.core.config import get_settings; s=get_settings(); print({"style": s.model_api_style, "base_url": s.openai_base_url, "model": s.openai_model, "reasoning_effort": s.model_reasoning_effort, "deepseek_key_configured": bool(s.deepseek_api_key), "openai_key_preserved": bool(s.openai_api_key), "active_key_configured": bool(s.model_api_key)})'
curl -fsS http://127.0.0.1:18010/health
```

再执行一次不写数据库、不触发 ntfy 的模型烟测，确认不是启发式 fallback：

```bash
docker compose --env-file .env -f deploy/docker-compose.prod.yml exec -T api python - <<'PY'
from app.services.structurer import build_structurer

result = build_structurer().structure("BTC 突破关键位置，短期观点偏多。")
if result.used_fallback:
    raise SystemExit(f"model fallback: {result.fallback_error}")
print({"summary_cn": result.summary_cn, "stance": result.stance, "symbols": result.symbols})
PY
```

不要为单纯切换模型重建 Web、MySQL、Redis、Collector 或 Nginx。只有容器内配置正确、健康检查通过、真实模型烟测没有 fallback 后才算切换完成。已经生成的历史 fallback Signal 不会自动重新分析。

### 迁移当前本地数据

迁移时先停 Collector，确保导出的 checkpoint、原帖和信号来自同一时点。数据直接通过 SSH 流式传输，不在磁盘留下含业务数据的 dump：

```bash
./scripts/collector-stop.sh
docker compose exec -T mysql sh -c \
  'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --routines --triggers --set-gtid-purged=OFF "$MYSQL_DATABASE"' | \
ssh deploy@www.yifanlab.cloud \
  'cd /home/deploy/kol-crawler && docker compose --env-file .env -f deploy/docker-compose.prod.yml exec -T mysql sh -c '\''exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"'\'''
./scripts/collector-start.sh
```

只有目标数据库为空或已经确认允许整体覆盖时才执行该命令。导入后至少核对 `subscriptions`、`raw_posts`、`signals`、`model_configs` 和 `notification_rules` 的行数。

### 安装 Nginx 路由

`deploy` 用户可以上传和运行容器，但服务器 Nginx 配置归 root 所有。项目提供的脚本只修改 `yifanlab.cloud` server 块：先备份原站点，安装 `/kol` snippet，执行 `nginx -t`，成功后才 reload；任何一步失败会自动恢复。

```bash
ssh deploy@www.yifanlab.cloud
cd /home/deploy/kol-crawler
sudo bash deploy/install-nginx.sh
```

安装后验证：

```bash
curl -I http://www.yifanlab.cloud/
curl -I http://www.yifanlab.cloud/kol
curl -I http://www.yifanlab.cloud/kol/login
```

根路径应继续返回原站点；`/kol` 未登录时应跳转到 `/kol/login`；登录页和 `/kol/_next/` 静态资源应返回 200。

当前证书和 HTTPS `/kol` 已可用，浏览器 API 地址必须保持为 `https://www.yifanlab.cloud/kol`，否则 HTTPS 登录页会因混合内容显示 `Failed to fetch`。HTTP 入口、Collector URL 和非 Secure Cookie 仍是待单独收口的兼容状态；后续强制 HTTPS 时再设置 `WEB_ORIGIN=https://www.yifanlab.cloud`、`COOKIE_SECURE=true`，重建 API，并把本机 `collector/.env` 的 `PUBLIC_API_URL` 改为 HTTPS。

### 回滚

应用回滚只操作 `kol-crawler` 项目，不运行全局 `docker system prune`：

```bash
cd /home/deploy/kol-crawler
docker compose --env-file .env -f deploy/docker-compose.prod.yml stop web api
```

Nginx 脚本成功时会输出原站点备份路径。恢复该备份、删除 `/etc/nginx/snippets/kol-crawler.conf` 后执行 `sudo nginx -t && sudo systemctl reload nginx`。数据库 volume 默认保留，不用 `docker compose down -v`。

## 公网 Docker

```bash
cp .env.example .env
# 编辑 .env，替换所有口令、hash、secret、topic 和模型配置
docker compose config --quiet
docker compose up --build -d
docker compose ps
curl -fsS http://localhost:8000/health
```

生产建议通过同域反向代理暴露 Web 与 `/api`，设置 `WEB_ORIGIN=https://your-domain`、`PUBLIC_API_BASE_URL=https://your-domain`、`COOKIE_SECURE=true`。不要直接公开 MySQL、Redis 端口。yifanlab 当前浏览器 API 已使用 HTTPS，HTTP 入口与 Cookie/Collector 的强制 HTTPS 收口仍待单独执行。

## 外部 MySQL

使用专用 schema 与最小权限用户，主机范围应收窄到 API 所在网络：

```sql
CREATE DATABASE kol_signal CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'kol_app'@'10.%' IDENTIFIED BY 'replace-with-strong-password';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX
  ON kol_signal.* TO 'kol_app'@'10.%';
```

将 `DATABASE_URL` 指向外部实例。API 启动时运行幂等迁移；需要人工审阅的 SQL 位于 `backend/migrations/`。Compose MySQL 只用于本地验收，不把本地 volume 当作生产备份。

## 本地采集机

安装 Python 3.12 与 OpenCLI，执行一次 `opencli twitter login`，再创建 `collector/.env`。确认 `COLLECTOR_AGENT_ID` 与公网一致、`COLLECTOR_TOKEN` 的 SHA-256 等于公网 `COLLECTOR_TOKEN_HASH` 后，在 macOS 执行 `./scripts/collector-launchd-install.sh`。LaunchAgent 会在登录后启动并在异常退出后重启；项目移动、Python 或 OpenCLI 路径变化后需重新安装 plist。系统不会自动登录 X。
