# 信号真实总数与可执行筛选设计

## 目标

修复首页“总样本数”被最新 100 条列表窗口截断的问题，并让“可执行”成为可操作的筛选条件：

- “总样本”显示数据库中的全部信号数量，不再使用当前列表长度。
- “实时情报”显示当前筛选条件匹配的总数量。
- 列表在数据库筛选后再按发帖时间倒序分页。
- 筛选栏提供“全部 / 仅可执行”，点击“可执行”统计卡也能切换同一状态。
- 新交互沿用现有 Graphite/Cyan 视觉和绿色可执行语义，不新增独立视觉体系。

## API 合约

保留 `GET /api/signals` 和现有 `items` 字段，新增向后兼容的分页与统计元数据：

```json
{
  "items": [],
  "total": 24,
  "overallTotal": 124,
  "actionableTotal": 9,
  "limit": 100,
  "offset": 0
}
```

- `total`：应用全部当前筛选条件后的信号数。
- `overallTotal`：不应用筛选条件的全库信号数。
- `actionableTotal`：应用除 `actionable` 以外的当前筛选条件后，其中可执行的信号数。
- `limit`、`offset`：本次实际分页参数；默认 `limit=100`、`offset=0`，并在入口约束
  `1 <= limit <= 100`、`offset >= 0`。

查询参数继续支持 `kol_id`、`asset`/`symbol`、`tag`、`stance`、`actionable`，并补充首页已有的 `platform`、`time_range`、`min_importance`。所有条件在数据库查询中、分页之前生效。

## 前端交互

`DashboardFilters` 增加 `actionableOnly: boolean`：

- 筛选栏新增“执行性”选择框，选项为“全部”和“仅可执行”。
- “可执行”统计卡改为原生 `button`；点击后切换 `actionableOnly`。
- 统计卡使用 `aria-pressed` 暴露选中状态，并用现有绿色边框和底色显示激活态。
- 筛选栏与统计卡读取同一份筛选状态，任一入口切换后另一处立即同步。
- 重置筛选时恢复“全部”。

首页调用分页信号接口：

- “实时情报”使用 `total`。
- “总样本”使用 `overallTotal`。
- “可执行”使用 `actionableTotal`。
- 列表标题显示当前页范围和匹配总数。
- 上一页、下一页按钮放在现有列表标题区域，复用小型次要按钮样式；筛选变化时回到第一页。

## 查询与排序

后端先建立公共筛选查询，再分别计算总数和读取当前页：

1. KOL 按 `Subscription.kol_profile_id` 过滤。
2. 平台按 `RawPost.platform` 过滤。
3. 方向将前端 `long / short / neutral / unknown` 映射为数据库值。
4. 标的、标签使用关联表 `EXISTS` 条件，避免连接产生重复信号。
5. 可执行按 `Signal.actionable` 过滤。
6. 时间范围按 `RawPost.published_at` 过滤。
7. 重要性按 `Signal.importance` 过滤；默认 `1` 不额外限制历史空值。
8. 最终按 `RawPost.published_at DESC, Signal.id DESC` 排序，再应用 `offset / limit`。

## 测试与验收

后端回归测试必须证明：

- 数据库超过 100 条时，`overallTotal` 和 `total` 返回真实数量，`items` 仍遵守分页大小。
- 可执行信号位于旧实现的前 100 条窗口之外时，`actionable=true` 仍能查到。
- 筛选发生在分页前，分页顺序仍按发帖时间倒序。
- 非法分页参数由 FastAPI 边界校验拒绝。

前端测试与验收必须证明：

- 请求参数正确携带 `actionable`、分页和现有筛选条件。
- 筛选状态可从筛选栏和统计卡双向切换并可重置。
- 总样本不再使用 `signals.length`。
- 统计卡可用键盘触发，并暴露正确的 `aria-pressed`。
- 桌面端与移动端保持现有布局，不出现新增控件突兀或溢出。

## 非目标

- 本次不改变信号生成、Collector、Agnes、ntfy、登录认证和数据库表结构。
- 不删除历史数据，不修改 10 分钟抓取周期。
- 不重做其他统计卡或 KOL、标的详情页。
