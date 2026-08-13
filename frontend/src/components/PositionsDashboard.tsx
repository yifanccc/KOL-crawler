"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, ChevronRight, RefreshCw } from "lucide-react";

import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Sidebar } from "@/components/Sidebar";
import { fetchPositionKols } from "@/lib/api";
import { leverageText, moneyText, pnlText } from "@/lib/positions";
import type { PositionKolSummary } from "@/lib/types";


const metricStatusLabels: Record<PositionKolSummary["metricsStatus"], string> = {
  COMPLETE: "完整估算",
  PARTIAL: "部分数据缺失",
  UNKNOWN: "暂不可估算",
};

function timeText(value?: string): string {
  if (!value) return "尚未同步";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function pnlClass(value?: string): string {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed === 0) return "";
  return parsed > 0 ? "value-positive" : "value-negative";
}

export function PositionsDashboard() {
  const [items, setItems] = useState<PositionKolSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async (background = false) => {
    if (background) setRefreshing(true);
    else setLoading(true);
    try {
      setItems(await fetchPositionKols());
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "持仓读取失败");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(true), 60_000);
    return () => window.clearInterval(timer);
  }, [load]);

  return (
    <div className="dashboard-shell">
      <Sidebar />
      <main className="positions-stage">
        <header className="positions-header">
          <div>
            <p className="eyebrow">Position Ledger</p>
            <h1>持仓监控</h1>
            <p>先看 KOL 账户汇总，再进入详情查看每个持仓和操作流水。</p>
          </div>
          <div className="positions-header-actions">
            <button
              type="button"
              disabled={loading || refreshing}
              onClick={() => void load(true)}
            >
              <RefreshCw
                className={refreshing ? "spin" : ""}
                size={15}
                aria-hidden="true"
              />
              {refreshing ? "刷新中" : "刷新数据"}
            </button>
          </div>
        </header>

        <div className="position-disclaimer" role="note">
          <AlertTriangle size={18} aria-hidden="true" />
          <div>
            <strong>仓位、开仓价与盈亏来自成交记录推算</strong>
            <span>保证金来自 Binance 组合详情，现价采用 Futures 标记价格；缺失字段会明确标注，不使用默认杠杆补齐。</span>
          </div>
        </div>

        {loading ? <div className="state-panel">正在读取 KOL 账户汇总...</div> : null}
        {!loading && error && items.length === 0 ? (
          <ErrorState message={error} onRetry={() => void load()} />
        ) : null}
        {!loading && error && items.length > 0 ? (
          <div className="state-panel error" role="alert">刷新失败：{error}</div>
        ) : null}
        {!loading && !error && items.length === 0 ? (
          <EmptyState
            title="暂无持仓监控 KOL"
            description="请从设置页的“配置订阅”添加 Binance Copy 组合。"
          />
        ) : null}

        {items.length > 0 ? (
          <section className="position-ledger" aria-label="KOL 持仓账户汇总">
            <header className="position-ledger-heading">
              <div>
                <p className="eyebrow">KOL Account Summary</p>
                <h2>KOL 账户总览</h2>
              </div>
              <span>{items.length} 个 KOL · 一人一行</span>
            </header>
            <div className="position-table-scroll">
              <table className="position-table position-summary-table">
                <thead>
                  <tr>
                    <th>KOL</th>
                    <th>保证金</th>
                    <th>持仓总金额</th>
                    <th>持仓保证金</th>
                    <th>持仓盈亏（估算）</th>
                    <th>有效杠杆</th>
                    <th>数据状态</th>
                    <th aria-label="查看详情" />
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.subscriptionId}>
                      <th scope="row">
                        <Link href={`/positions/${item.subscriptionId}`}>
                          <strong>{item.kolName}</strong>
                          <span>Portfolio {item.accountId}</span>
                        </Link>
                      </th>
                      <td>{moneyText(item.marginBalance)}</td>
                      <td>{moneyText(item.totalPositionNotional)}</td>
                      <td>{moneyText(item.positionMargin)}</td>
                      <td className={pnlClass(item.estimatedPnl)}>
                        {pnlText(item.estimatedPnl)}
                      </td>
                      <td>{leverageText(item.effectiveLeverage)}</td>
                      <td>
                        <span className={`position-quality quality-${item.metricsStatus.toLowerCase()}`}>
                          {metricStatusLabels[item.metricsStatus]}
                        </span>
                        <small>
                          {item.activePositionCount} 个持仓
                          {item.uncertainPositionCount
                            ? ` · ${item.uncertainPositionCount} 个待确认`
                            : ""}
                          {` · ${timeText(item.updatedAt)}`}
                        </small>
                      </td>
                      <td>
                        <Link
                          className="position-row-open"
                          href={`/positions/${item.subscriptionId}`}
                          aria-label={`查看 ${item.kolName} 持仓详情`}
                        >
                          <ChevronRight size={17} aria-hidden="true" />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ) : null}
      </main>
    </div>
  );
}
