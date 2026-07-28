# KOL Signal Crawler

金融 KOL 情报系统由两部分组成：公网 Docker 负责认证、存储、中文结构化分析与 Dashboard；本机 `collector` 进程用本地 OpenCLI 登录态采集 X，并将 Outbox 中的原帖以机器 token 上送。浏览器 Cookie、模型 key 与 X 登录态永不跨越这条边界。

## 快速启动

1. `cp .env.example .env`，按 [配置说明](docs/configuration.md) 生成管理员 bcrypt hash、JWT secret 和 collector token hash；根 `.env` 供 Docker 使用。
2. `docker compose up --build -d` 启动公网部分。
3. 在本机执行 `cp collector/.env.example collector/.env`，填写与根 `.env` hash 配对的明文 `COLLECTOR_TOKEN`；Binance 采集还需要填写本机 Chrome/Chromium 路径。
4. macOS 执行 `./scripts/collector-launchd-install.sh` 安装常驻 Collector，并用 `./scripts/collector-status.sh` 和 Admin 的新鲜 heartbeat 双重确认。
5. 访问 Web，登录后查看 `/admin` 的订阅和 Collector 心跳。

完整部署、恢复和验收命令见 [部署](docs/deployment.md)、[运维](docs/operations.md) 与 [验收记录](docs/verification.md)。

`www.yifanlab.cloud/kol` 使用独立的 `deploy/docker-compose.prod.yml` 和 Nginx snippet；不要用根目录的本地 Compose 文件直接覆盖服务器。当前 HTTP 部署步骤、一次性 Nginx sudo 命令、数据迁移与回滚方式均记录在部署文档中。

## 常用命令

```bash
docker compose config --quiet
docker compose up --build -d
./scripts/collector-launchd-install.sh
./scripts/collector-status.sh
cd backend && pytest -q
cd ../collector && python -m pytest -q
cd ../frontend && npm run build
```
