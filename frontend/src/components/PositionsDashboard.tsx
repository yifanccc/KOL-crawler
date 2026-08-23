"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ArrowUpRight, Clock3, RefreshCw } from "lucide-react";

import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { KolAvatar } from "@/components/KolAvatar";
import { PlatformMark } from "@/components/PlatformMark";
import { PositionMetricGuide } from "@/components/PositionMetricGuide";
import { Sidebar } from "@/components/Sidebar";
import { fetchPositionKols } from "@/lib/api";
import { accountMultipleText, moneyText, pnlText } from "@/lib/positions";
import type { PositionKolSummary } from "@/lib/types";


const metricStatusLabels: Record<PositionKolSummary["metricsStatus"], string> = {
  COMPLETE: "指标齐全",
  PARTIAL: "指标有缺口",
  UNKNOWN: "暂无指标",
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
        <header className="positions-header positions-overview-header">
          <div>
            <p className="eyebrow">Position Monitor</p>
            <h1>持仓监控</h1>
            <p>一张卡看清一个 KOL 的资金规模、可估算仓位敞口与浮动盈亏。</p>
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

        {loading ? <div className="state-panel">正在读取 KOL 仓位...</div> : null}
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
          <section className="position-kol-grid" aria-label="KOL 持仓核心指标">
            {items.map((item) => (
              <Link
                className="position-kol-card"
                href={`/positions/${item.subscriptionId}`}
                key={item.subscriptionId}
              >
                <header>
                  <div className="position-kol-identity">
                    <KolAvatar
                      kol={{
                        id: item.kolId,
                        name: item.kolName,
                        platform: item.platform,
                      }}
                      platform={item.platform}
                      size={46}
                    />
                    <div>
                      <h2>{item.kolName}</h2>
                      <p>
                        <PlatformMark platform={item.platform} withLabel />
                        <span>Portfolio {item.accountId}</span>
                      </p>
                    </div>
                  </div>
                  <span className={`position-quality quality-${item.metricsStatus.toLowerCase()}`}>
                    {metricStatusLabels[item.metricsStatus]}
                  </span>
                </header>

                <div className="position-kol-card-body">
                  <div className="position-kol-pnl">
                    <span>当前预计盈亏</span>
                    <strong className={pnlClass(item.estimatedPnl)}>
                      {pnlText(item.estimatedPnl)}
                    </strong>
                    <small>未计手续费与资金费</small>
                  </div>
                  <dl className="position-kol-metrics">
                    <div>
                      <dt>账户保证金余额</dt>
                      <dd>{moneyText(item.marginBalance)}</dd>
                    </div>
                    <div>
                      <dt>已估算持仓总额</dt>
                      <dd>{moneyText(item.totalPositionNotional)}</dd>
                    </div>
                    <div>
                      <dt>仓位倍数（估算）</dt>
                      <dd>{accountMultipleText(item.totalPositionNotional, item.marginBalance)}</dd>
                    </div>
                  </dl>
                </div>

                <footer>
                  <span>
                    <Clock3 size={13} aria-hidden="true" />
                    更新于 {timeText(item.updatedAt)}
                    {item.uncertainPositionCount
                      ? ` · ${item.uncertainPositionCount} 个仓位待确认`
                      : ""}
                  </span>
                  <strong>
                    查看仓位详情 <ArrowUpRight size={15} aria-hidden="true" />
                  </strong>
                </footer>
              </Link>
            ))}
          </section>
        ) : null}

        {items.length > 0 ? <PositionMetricGuide /> : null}
      </main>
    </div>
  );
}
