"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, ArrowLeft, RefreshCw } from "lucide-react";

import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Sidebar } from "@/components/Sidebar";
import { fetchPositionKolDetail, fetchPositionOperations } from "@/lib/api";
import {
  leverageText,
  moneyText,
  pnlText,
  priceText,
  quantityText,
} from "@/lib/positions";
import type {
  PositionKolDetail as PositionKolDetailData,
  PositionOperationPage,
  PositionSnapshot,
} from "@/lib/types";


const actionLabels = {
  OPEN: "开仓",
  ADD: "加仓",
  REDUCE: "减仓",
  CLOSE: "平仓",
  REVERSE: "反手",
  CORRECTION: "交易修订",
};
const sideLabels = { LONG: "多", SHORT: "空", FLAT: "空仓", UNKNOWN: "未知" };
const statusLabels = { ACTIVE: "持仓中", FLAT: "已平仓", STALE: "数据陈旧", UNKNOWN: "待确认" };
const PAGE_SIZE = 50;

function dateTimeText(value?: string): string {
  if (!value) return "未知";
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

function sideClass(side: PositionSnapshot["side"] | "LONG" | "SHORT" | "UNKNOWN") {
  if (side === "LONG") return "side-long-text";
  if (side === "SHORT") return "side-short-text";
  return "";
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
  return (
    <div className="dashboard-shell">
      <Sidebar />
      <main className="positions-stage">
        <header className="positions-header">
          <div>
            <Link className="back-link" href="/positions">
              <ArrowLeft size={14} aria-hidden="true" />返回 KOL 总览
            </Link>
            <p className="eyebrow">KOL Position Detail</p>
            <h1>{summary?.kolName || "KOL 持仓详情"}</h1>
            <p>{summary ? `Binance Copy · Portfolio ${summary.accountId}` : "正在读取组合信息"}</p>
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
          <section className="kol-position-strip" aria-label="KOL 账户核心数据">
            <dl>
              <div><dt>保证金</dt><dd>{moneyText(summary.marginBalance)}</dd></div>
              <div><dt>持仓总金额</dt><dd>{moneyText(summary.totalPositionNotional)}</dd></div>
              <div><dt>持仓保证金</dt><dd>{moneyText(summary.positionMargin)}</dd></div>
              <div><dt>持仓盈亏（估算）</dt><dd className={valueClass(summary.estimatedPnl)}>{pnlText(summary.estimatedPnl)}</dd></div>
              <div><dt>有效杠杆</dt><dd>{leverageText(summary.effectiveLeverage)}</dd></div>
            </dl>
          </section>
        ) : null}

        <nav className="positions-tabs" aria-label="KOL 持仓详情子页面">
          <Link className={initialView === "positions" ? "active" : ""} href={`/positions/${subscriptionId}`}>
            当前持仓{detail ? ` ${detail.positions.length}` : ""}
          </Link>
          <Link className={initialView === "operations" ? "active" : ""} href={`/positions/${subscriptionId}?view=operations`}>
            操作记录{operations.total ? ` ${operations.total}` : ""}
          </Link>
        </nav>

        <div className="position-disclaimer" role="note">
          <AlertTriangle size={18} aria-hidden="true" />
          <div>
            <strong>所有带“估算”的字段都不是交易所真实持仓回报</strong>
            <span>操作记录来自已成交订单；当前持仓由这些记录连续推演，历史缺口会降低可信度。</span>
          </div>
        </div>

        {loading ? <div className="state-panel">正在读取持仓账本...</div> : null}
        {!loading && error && !detail ? <ErrorState message={error} onRetry={() => void load(0)} /> : null}
        {!loading && error && detail ? <div className="state-panel error">刷新失败：{error}</div> : null}

        {!loading && detail && initialView === "positions" ? (
          detail.positions.length ? (
            <section className="position-ledger" aria-label="当前持仓">
              <header className="position-ledger-heading">
                <div><p className="eyebrow">Current Positions</p><h2>当前持仓</h2></div>
                <span>一仓一行 · 行情每 10 分钟更新</span>
              </header>
              <div className="position-table-scroll">
                <table className="position-table position-detail-table">
                  <thead><tr><th>品种</th><th>方向</th><th>当前价格</th><th>开仓价格</th><th>持仓数量</th><th>持仓金额</th><th>杠杆</th><th>预计盈亏</th><th>状态</th></tr></thead>
                  <tbody>
                    {detail.positions.map((position) => (
                      <tr key={`${position.symbol}:${position.positionSide}`}>
                        <th scope="row"><strong>{position.symbol}</strong><span>{dateTimeText(position.asOfEventTime)}</span></th>
                        <td className={sideClass(position.side)}>{sideLabels[position.side]}</td>
                        <td>{priceText(position.currentPrice)}</td>
                        <td>{priceText(position.entryPrice)}</td>
                        <td>{quantityText(position.quantity)}</td>
                        <td>{moneyText(position.notional)}</td>
                        <td>{leverageText(position.leverage)}</td>
                        <td className={valueClass(position.estimatedPnl)}>{pnlText(position.estimatedPnl)}</td>
                        <td><span className={`position-state state-${position.status.toLowerCase()}`}>{statusLabels[position.status]}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ) : (
            <EmptyState title="暂无当前持仓" description="没有推测中的活动仓位，或成交历史暂时不足以建立仓位。" />
          )
        ) : null}

        {!loading && detail && initialView === "operations" ? (
          operations.items.length ? (
            <section className="position-ledger" aria-label="持仓操作记录">
              <header className="position-ledger-heading">
                <div><p className="eyebrow">Operation Tape</p><h2>操作记录</h2></div>
                <span>共 {operations.total} 条 · 最新在前</span>
              </header>
              <div className="position-table-scroll">
                <table className="position-table position-operation-table">
                  <thead><tr><th>操作时间</th><th>品种</th><th>操作</th><th>方向</th><th>开仓/平仓价格</th><th>开仓/平仓数量</th><th>金额</th></tr></thead>
                  <tbody>
                    {operations.items.map((operation) => (
                      <tr key={`${operation.sourceRecordId}:${operation.revision}`}>
                        <th scope="row">{dateTimeText(operation.eventTime)}</th>
                        <td><strong>{operation.symbol}</strong></td>
                        <td>{actionLabels[operation.action]}</td>
                        <td className={sideClass(operation.positionSide)}>{sideLabels[operation.positionSide]}</td>
                        <td>{priceText(operation.price)}</td>
                        <td>{quantityText(operation.quantity)}</td>
                        <td>{moneyText(operation.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
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
      </main>
    </div>
  );
}
