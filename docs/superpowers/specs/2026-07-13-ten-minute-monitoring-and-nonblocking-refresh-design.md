# 10 分钟监控与非阻断刷新设计

## 目标

1. 本机 Collector 的配置/调度循环由 60 秒改为 600 秒。
2. 所有未删除的现有订阅统一改为 10 分钟。
3. 后端、前端表单和初始化流程中的新增订阅默认间隔统一为 10 分钟。
4. 新增订阅默认使用实施时 Serenity（X handle：`aleabitoreddit`）当前 System prompt、User prompt 和 Output Schema 的固定快照。
5. 页面后台刷新时保留现有内容和交互能力，不再切换到全屏 Loading 或 Error 状态。
6. 模型分析在后台工作线程执行，不能阻塞 FastAPI 事件循环和 Dashboard API。

## 调度与默认值

- `collector/.env`、`collector/.env.example` 和 Collector 配置类的 `CONFIG_POLL_SECONDS` 默认值改为 `600`。
- 生产数据库中所有 `deleted_at IS NULL` 的订阅将批量更新为 `interval_minutes = 10`。
- `Subscription.interval_minutes` 的模型默认值、创建接口默认值、前端新增表单默认值和 bootstrap 默认订阅均改为 10。
- Collector 启动后仍按每个订阅自己的 `intervalMinutes` 计算下一次检查；首次启动可以立即执行一次，完成后再等待 10 分钟。
- Dashboard 的数据刷新仍保持 60 秒。它不是抓取任务，只负责及时显示已经完成分析的新数据。

## 新增订阅提示词

- 采用用户选择的固定快照方案，不在新增时查询 Serenity 订阅。
- 实施时从生产 Serenity 订阅读取当前 `system_prompt`、`user_prompt` 和 `output_schema_json`，写入版本控制中的默认提示词常量。
- Admin `config-options` 返回该固定默认值，前端“新建订阅”表单据此预填。
- 创建接口即使调用方省略提示词，也会在服务端写入相同固定默认值，避免只依赖前端。
- 以后修改 Serenity 的独立提示词不会自动改变新增订阅默认值；若要更新默认快照，需要显式修改代码并重新发布。

## 页面不可用问题

### 根因

- 首页 `loadDashboard` 和共享 `useMarketData.reload` 每次 60 秒后台刷新都会执行 `setLoading(true)`。
- 页面因此用全屏 `LoadingState` 替换现有内容；后台请求失败时又会用 `ErrorState` 替换已有数据。
- API 的 `analysis_loop` 还会在事件循环内同步执行数据库处理和模型 HTTP 请求；Collector 上传新帖后，较慢的模型请求会阻塞同一进程中的页面 API。
- 前端刷新周期与 Collector 原先的一分钟循环接近，再叠加后端分析阻塞，因此视觉上表现为“Collector 收集时页面不可用”。

### 修复

- 区分首次/人工重试的阻断加载与定时后台刷新。
- 首次加载没有可用数据时继续显示 Loading；首次失败继续显示 Error 与重试入口。
- 已经成功加载过数据后，定时刷新不修改阻断 loading 状态。
- 后台刷新成功时原子替换数据并清除旧错误。
- 后台刷新失败时保留最后一次成功数据和现有交互，不显示全屏 Error。
- 后端用 `asyncio.to_thread` 执行完整分析批次，并在该工作线程内创建和关闭 SQLAlchemy Session；模型分析期间事件循环继续服务健康检查和 Dashboard 请求。
- 不增加新的刷新动画、Toast 或状态组件，保持现有视觉风格。

## 测试与验收

- 后端测试覆盖：创建接口省略间隔时默认 10 分钟；配置选项返回固定 Serenity 提示词快照；新订阅省略提示词时服务端写入快照；慢分析批次不阻塞事件循环。
- Collector 测试覆盖：未配置 `CONFIG_POLL_SECONDS` 时默认 600 秒；订阅成功执行后按 10 分钟计算下一次检查。
- 前端增加可独立测试的刷新策略，覆盖首次加载为阻断模式、已有数据的后台刷新为非阻断模式。
- 运行后端、Collector 全量测试和前端 production build。
- 生产验收：所有未删除订阅均为 10 分钟；Collector launchd 读取 `CONFIG_POLL_SECONDS=600`；heartbeat 健康且 Outbox 为 0。
- 浏览器验收：后台 API 请求进行期间，首页、KOL 页和标的页已有内容持续可见且可交互。

## 部署与回滚

- 继续使用服务器端 `deploy/docker-compose.prod.yml` 在线构建，Python 包源固定走腾讯云镜像。
- API 与 Web 分别重建；MySQL、Redis 和 Nginx 不重建、不修改。只切换 `OPENAI_MODEL` 时无需 build，只需备份生产 `.env` 后强制重建 API 容器。
- 数据更新只修改未删除订阅的 `interval_minutes`，不修改 checkpoint、提示词、历史帖子或信号。
- 回滚应用时使用部署前 API/Web 镜像；回滚配置时把 `CONFIG_POLL_SECONDS` 和订阅间隔恢复为发布前值。提示词快照不影响已有订阅。
