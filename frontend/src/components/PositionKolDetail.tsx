"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, Clock3, RefreshCw } from "lucide-react";

import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { PositionMetricGuide } from "@/components/PositionMetricGuide";
import { Sidebar } from "@/components/Sidebar";
import { fetchPositionKolDetail, fetchPositionOperations } from "@/lib/api";
import {
  accountMultipleText,
  currentPositions,
  moneyText,
  multipleText,
  pnlText,
  priceText,
  quantityText,
  summarizePositionExposure,
} from "@/lib/positions";
import type {
  PositionKolDetail as PositionKolDetailData,
  PositionKolSummary,
  PositionOperationPage,
} from "@/lib/types";


const actionLabels = {
  OPEN: "开仓",
  ADD: "加仓",
  REDUCE: "减仓",
  CLOSE: "平仓",
  REVERSE: "反手",
  CORRECTION: "交易修订",
};
const sideLabels = { LONG: "多", SHORT: "空", FLAT: "空仓", UNKNOWN: "方向待确认" };
const statusLabels = { ACTIVE: "持仓中", FLAT: "已平仓", STALE: "数据陈旧", UNKNOWN: "待确认" };
const metricStatusLabels: Record<PositionKolSummary["metricsStatus"], string> = {
  COMPLETE: "指标齐全",
  PARTIAL: "指标有缺口",
  UNKNOWN: "暂无指标",
};
const PAGE_SIZE = 50;

function dateTimeText(value?: string): string {
  if (!value) return "时间未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function valueClass(value?: string): string {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed === 0) return "";
  return parsed > 0 ? "value-positive" : "value-negative";
}

function numberMoneyText(value: number | null): string {
  return value === null ? "暂不可估算" : moneyText(String(value));
}

export function PositionKolDetail({
  subscriptionId,
  initialView,
}: {
  subscriptionId: number;
  initialView: "positions" | "operations";
}) {
  const [detail, setDetail] = useState<PositionKolDetailData | null>(null);
  const [operations, setOperations] = useState<PositionOperationPage>({
    items: [],
    total: 0,
    limit: PAGE_SIZE,
    offset: 0,
  });
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async (nextOffset: number, background = false) => {
    if (background) setRefreshing(true);
    else setLoading(true);
    try {
      const [nextDetail, nextOperations] = await Promise.all([
        fetchPositionKolDetail(subscriptionId),
        fetchPositionOperations(subscriptionId, {
          limit: PAGE_SIZE,
          offset: nextOffset,
        }),
      ]);
      setDetail(nextDetail);
      setOperations(nextOperations);
      setOffset(nextOffset);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "KOL 持仓详情读取失败");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [subscriptionId]);

  useEffect(() => {
    void load(offset);
    const timer = window.setInterval(() => void load(offset, true), 60_000);
    return () => window.clearInterval(timer);
  }, [load, offset]);

  const summary = detail?.summary;
  const positions = detail ? currentPositions(detail.positions) : [];
  const exposure = detail
    ? summarizePositionExposure(positions, summary?.marginBalance)
    : null;
  const exposureExclusionText = exposure
    ? [
        exposure.unresolvedCount
          ? `${exposure.unresolvedCount} 个方向或状态待确认`
          : "",
        exposure.missingNotionalCount
          ? `${exposure.missingNotionalCount} 个缺少名义金额`
          : "",
      ].filter(Boolean).join("，")
    : "";

  return (
    <div className="dashboard-shell">
      <Sidebar />
      <main className="positions-stage">
        <header className="positions-header position-detail-header">
          <div>
            <Link className="back-link" href="/positions">
              <ArrowLeft size={14} aria-hidden="true" />返回持仓监控
            </Link>
            <p className="eyebrow">KOL Position Detail</p>
            <h1>{summary?.kolName || "KOL 持仓详情"}</h1>
            <p>
              {summary
                ? `Binance Copy · Portfolio ${summary.accountId} · 由成交记录持续推算`
                : "正在读取组合信息"}
            </p>
          </div>
          <div className="positions-header-actions">
            <button
              type="button"
              disabled={loading || refreshing}
              onClick={() => void load(offset, true)}
            >
              <RefreshCw className={refreshing ? "spin" : ""} size={15} aria-hidden="true" />
              {refreshing ? "刷新中" : "刷新数据"}
            </button>
          </div>
        </header>

        {summary ? (
          <>
            <section className="position-account-overview" aria-label="KOL 账户核心指标">
              <header className="position-section-heading">
                <div>
                  <p className="eyebrow">Account Snapshot</p>
                  <h2>账户概况</h2>
                </div>
                <div className="position-account-state">
                  <span className={`position-quality quality-${summary.metricsStatus.toLowerCase()}`}>
                    {metricStatusLabels[summary.metricsStatus]}
                  </span>
                  <small>更新于 {dateTimeText(summary.updatedAt)}</small>
                </div>
              </header>

              <div className="position-account-core">
                <div className="position-account-pnl">
                  <span>当前预计盈亏</span>
                  <strong className={valueClass(summary.estimatedPnl)}>
                    {pnlText(summary.estimatedPnl)}
                  </strong>
                  <small>未计手续费与资金费</small>
                </div>
                <dl>
                  <div>
                    <dt>账户保证金余额</dt>
                    <dd>{moneyText(summary.marginBalance)}</dd>
                  </div>
                  <div>
                    <dt>已估算持仓总额</dt>
                    <dd>{moneyText(summary.totalPositionNotional)}</dd>
                  </div>
                  <div>
                    <dt>仓位倍数（估算）</dt>
                    <dd>{accountMultipleText(summary.totalPositionNotional, summary.marginBalance)}</dd>
                  </div>
                </dl>
              </div>
            </section>

            {exposure ? (
              <section className="position-exposure-summary" aria-label="多空仓位汇总">
                <header className="position-section-heading">
                  <div>
                    <p className="eyebrow">Exposure Split</p>
                    <h2>仓位汇总</h2>
                  </div>
                  <span>按可估算名义金额统计</span>
                </header>
                <div className="position-exposure-body">
                  <article className="position-exposure-side exposure-long">
                    <span>多头仓位</span>
                    <strong>{numberMoneyText(exposure.long.notional)}</strong>
                    <small>
                      {exposure.long.count} 个 · 占账户 {multipleText(exposure.long.accountMultiple)}
                    </small>
                  </article>
                  <div className="position-exposure-rail-wrap">
                    <div
                      className="position-exposure-rail"
                      aria-label={
                        exposure.longShare === null
                          ? "多空名义金额暂不可估算"
                          : `多头 ${Math.round(exposure.longShare * 100)}%，空头 ${Math.round((exposure.shortShare ?? 0) * 100)}%`
                      }
                    >
                      {exposure.longShare !== null ? (
                        <>
                          <span
                            className="exposure-rail-long"
                            style={{ width: `${exposure.longShare * 100}%` }}
                          />
                          <span
                            className="exposure-rail-short"
                            style={{ width: `${(exposure.shortShare ?? 0) * 100}%` }}
                          />
                        </>
                      ) : (
                        <span className="exposure-rail-empty" />
                      )}
                    </div>
                    <div>
                      <span>多 {exposure.longShare === null ? "—" : `${Math.round(exposure.longShare * 100)}%`}</span>
                      <span>空 {exposure.shortShare === null ? "—" : `${Math.round(exposure.shortShare * 100)}%`}</span>
                    </div>
                  </div>
                  <article className="position-exposure-side exposure-short">
                    <span>空头仓位</span>
                    <strong>{numberMoneyText(exposure.short.notional)}</strong>
                    <small>
                      {exposure.short.count} 个 · 占账户 {multipleText(exposure.short.accountMultiple)}
                    </small>
                  </article>
                </div>
                {exposureExclusionText ? (
                  <p>{exposureExclusionText}，未计入多空金额和占比。</p>
                ) : null}
              </section>
            ) : null}
          </>
        ) : null}

        <nav className="positions-tabs" aria-label="KOL 持仓详情子页面">
          <Link className={initialView === "positions" ? "active" : ""} href={`/positions/${subscriptionId}`}>
            当前持仓{detail ? ` ${positions.length}` : ""}
          </Link>
          <Link className={initialView === "operations" ? "active" : ""} href={`/positions/${subscriptionId}?view=operations`}>
            操作记录{operations.total ? ` ${operations.total}` : ""}
          </Link>
        </nav>

        {loading ? <div className="state-panel">正在读取持仓账本...</div> : null}
        {!loading && error && !detail ? <ErrorState message={error} onRetry={() => void load(0)} /> : null}
        {!loading && error && detail ? <div className="state-panel error">刷新失败：{error}</div> : null}

        {!loading && detail && initialView === "positions" ? (
          positions.length ? (
            <section className="position-detail-section" aria-label="当前持仓">
              <header className="position-section-heading">
                <div><p className="eyebrow">Current Positions</p><h2>当前持仓</h2></div>
                <span>{positions.length} 个仓位 · 标记价格每 10 分钟更新</span>
              </header>
              <div className="position-holding-list">
                {positions.map((position) => (
                  <article
                    className={`position-holding-card holding-${position.side.toLowerCase()}`}
                    key={`${position.symbol}:${position.positionSide}`}
                  >
                    <header>
                      <div>
                        <h3>{position.symbol}</h3>
                        <p>
                          <span className={`position-side-badge badge-${position.side.toLowerCase()}`}>
                            {sideLabels[position.side]}
                          </span>
                          <span className={`position-state state-${position.status.toLowerCase()}`}>
                            {statusLabels[position.status]}
                          </span>
                        </p>
                      </div>
                      {position.estimatedPnl !== undefined ? (
                        <div className="position-holding-pnl">
                          <span>预计盈亏</span>
                          <strong className={valueClass(position.estimatedPnl)}>
                            {pnlText(position.estimatedPnl)}
                          </strong>
                        </div>
                      ) : null}
                    </header>

                    <dl>
                      {position.currentPrice !== undefined ? (
                        <div><dt>标记价格</dt><dd>{priceText(position.currentPrice)}</dd></div>
                      ) : null}
                      {position.entryPrice !== undefined ? (
                        <div><dt>推算开仓价</dt><dd>{priceText(position.entryPrice)}</dd></div>
                      ) : null}
                      {position.quantity !== undefined ? (
                        <div><dt>推算持仓数量</dt><dd>{quantityText(position.quantity)}</dd></div>
                      ) : null}
                      {position.notional !== undefined ? (
                        <div><dt>名义金额</dt><dd>{moneyText(position.notional)}</dd></div>
                      ) : null}
                    </dl>

                    <footer>
                      {position.asOfEventTime ? (
                        <span><Clock3 size={13} aria-hidden="true" />最近操作 {dateTimeText(position.asOfEventTime)}</span>
                      ) : null}
                      {position.priceUpdatedAt ? (
                        <span><RefreshCw size={13} aria-hidden="true" />标记价 {dateTimeText(position.priceUpdatedAt)}</span>
                      ) : null}
                    </footer>
                  </article>
                ))}
              </div>
            </section>
          ) : (
            <EmptyState title="暂无当前持仓" description="没有推测中的活动仓位，或成交历史暂时不足以建立仓位。" />
          )
        ) : null}

        {!loading && detail && initialView === "operations" ? (
          operations.items.length ? (
            <section className="position-detail-section" aria-label="持仓操作记录">
              <header className="position-section-heading">
                <div><p className="eyebrow">Operation Timeline</p><h2>操作记录</h2></div>
                <span>共 {operations.total} 条 · 最新在前</span>
              </header>
              <ol className="position-operation-list">
                {operations.items.map((operation) => (
                  <li key={`${operation.sourceRecordId}:${operation.revision}`}>
                    <span className={`position-operation-marker marker-${operation.positionSide.toLowerCase()}`} />
                    <article>
                      <header>
                        <div>
                          <span className="position-action-badge">{actionLabels[operation.action]}</span>
                          <span className={`position-side-badge badge-${operation.positionSide.toLowerCase()}`}>
                            {sideLabels[operation.positionSide]}
                          </span>
                        </div>
                        <time dateTime={operation.eventTime}>{dateTimeText(operation.eventTime)}</time>
                      </header>
                      <h3>{operation.symbol}</h3>
                      <dl>
                        {operation.price !== undefined ? (
                          <div><dt>成交均价</dt><dd>{priceText(operation.price)}</dd></div>
                        ) : null}
                        {operation.quantity !== undefined ? (
                          <div><dt>成交数量</dt><dd>{quantityText(operation.quantity)}</dd></div>
                        ) : null}
                        {operation.amount !== undefined ? (
                          <div><dt>成交金额</dt><dd>{moneyText(operation.amount)}</dd></div>
                        ) : null}
                        {operation.realizedPnl !== undefined && Number(operation.realizedPnl) !== 0 ? (
                          <div>
                            <dt>已实现盈亏</dt>
                            <dd className={valueClass(operation.realizedPnl)}>{pnlText(operation.realizedPnl)}</dd>
                          </div>
                        ) : null}
                      </dl>
                    </article>
                  </li>
                ))}
              </ol>
              <footer className="position-pagination">
                <button type="button" disabled={offset === 0 || refreshing} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>上一页</button>
                <span>{offset + 1}–{Math.min(offset + operations.items.length, operations.total)} / {operations.total}</span>
                <button type="button" disabled={offset + PAGE_SIZE >= operations.total || refreshing} onClick={() => setOffset(offset + PAGE_SIZE)}>下一页</button>
              </footer>
            </section>
          ) : (
            <EmptyState title="暂无操作记录" description="完成成交基线后，新抓取到的已成交操作会显示在这里。" />
          )
        ) : null}

        {detail ? <PositionMetricGuide /> : null}
      </main>
    </div>
  );
}
