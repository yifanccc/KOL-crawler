"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Clock3,
  RefreshCw,
  Settings,
  ShieldAlert,
} from "lucide-react";

import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Sidebar } from "@/components/Sidebar";
import { fetchPositions } from "@/lib/api";
import { currentPositions, summarizePositions } from "@/lib/positions";
import type { PositionSnapshot } from "@/lib/types";


const sideLabels: Record<PositionSnapshot["side"], string> = {
  LONG: "多头",
  SHORT: "空头",
  FLAT: "空仓",
  UNKNOWN: "方向未知",
};

const statusLabels: Record<PositionSnapshot["status"], string> = {
  ACTIVE: "持仓中",
  FLAT: "已平仓",
  STALE: "数据陈旧",
  UNKNOWN: "状态未知",
};

const confidenceLabels: Record<PositionSnapshot["confidence"], string> = {
  HIGH: "高",
  MEDIUM: "中",
  LOW: "低",
  UNKNOWN: "未知",
};

function timeText(value?: string): string {
  if (!value) return "未知";
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

export function PositionsDashboard() {
  const [positions, setPositions] = useState<PositionSnapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async (background = false) => {
    if (background) setRefreshing(true);
    else setLoading(true);
    try {
      setPositions(await fetchPositions());
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

  const visiblePositions = useMemo(
    () => currentPositions(positions),
    [positions],
  );
  const summary = useMemo(() => summarizePositions(positions), [positions]);
  const latestUpdate = positions.reduce<string | undefined>((latest, position) => {
    if (!latest || position.updatedAt > latest) return position.updatedAt;
    return latest;
  }, undefined);

  return (
    <div className="dashboard-shell">
      <Sidebar />
      <main className="positions-stage">
        <header className="positions-header">
          <div>
            <p className="eyebrow">Inferred Positions</p>
            <h1>持仓监控</h1>
            <p>基于私域带单员成交记录推测的当前仓位。</p>
          </div>
          <div className="positions-header-actions">
            <Link href="/admin/binance-copy">
              <Settings size={15} aria-hidden="true" />配置监控
            </Link>
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
              {refreshing ? "刷新中" : "刷新"}
            </button>
          </div>
        </header>

        <nav className="positions-tabs" aria-label="持仓监控子页面">
          <Link className="active" href="/positions">当前持仓</Link>
          <Link href="/positions/history">成交变化</Link>
        </nav>

        <div className="position-disclaimer" role="note">
          <AlertTriangle size={18} aria-hidden="true" />
          <div>
            <strong>这是推测持仓，不是交易所实时持仓</strong>
            <span>成交历史不完整、接口受限或采集延迟都可能导致数量与真实仓位不同。</span>
          </div>
        </div>

        <section className="position-metrics" aria-label="持仓概览">
          <article>
            <Activity size={18} aria-hidden="true" />
            <div><strong>{summary.current}</strong><span>当前仓位</span></div>
          </article>
          <article>
            <ShieldAlert size={18} aria-hidden="true" />
            <div><strong>{summary.uncertain}</strong><span>需谨慎确认</span></div>
          </article>
          <article>
            <Clock3 size={18} aria-hidden="true" />
            <div><strong>{timeText(latestUpdate)}</strong><span>最近更新</span></div>
          </article>
        </section>

        {loading ? <div className="state-panel">正在读取推测持仓...</div> : null}
        {!loading && error && positions.length === 0 ? (
          <ErrorState message={error} onRetry={() => void load()} />
        ) : null}
        {!loading && error && positions.length > 0 ? (
          <div className="state-panel error" role="alert">刷新失败：{error}</div>
        ) : null}
        {!loading && !error && visiblePositions.length === 0 ? (
          <EmptyState
            title="暂无当前持仓"
            description="采集器完成首轮成交基线并同步后，推测仓位会显示在这里。"
          />
        ) : null}

        {visiblePositions.length > 0 ? (
          <section className="position-card-grid" aria-label="当前推测持仓">
            {visiblePositions.map((position) => (
              <article
                className={`position-card position-${position.status.toLowerCase()} side-${position.side.toLowerCase()}`}
                key={`${position.subscriptionId}:${position.symbol}:${position.positionSide}`}
              >
                <header>
                  <div>
                    <span>{position.kolName}</span>
                    <small>Portfolio {position.accountId}</small>
                  </div>
                  <em>{statusLabels[position.status]}</em>
                </header>
                <div className="position-symbol-row">
                  <strong>{position.symbol}</strong>
                  <span>{sideLabels[position.side]}</span>
                </div>
                <dl>
                  <div><dt>推测数量</dt><dd>{position.quantity || "未知"}</dd></div>
                  <div><dt>置信度</dt><dd>{confidenceLabels[position.confidence]}</dd></div>
                  <div><dt>最后成交</dt><dd>{timeText(position.asOfEventTime)}</dd></div>
                  <div><dt>采集更新</dt><dd>{timeText(position.updatedAt)}</dd></div>
                </dl>
                {position.status === "STALE" ? (
                  <p>自 {timeText(position.staleSince)} 起未能确认最新成交记录。</p>
                ) : null}
                {position.status === "UNKNOWN" ? (
                  <p>检测到历史缺口，当前方向或数量不能可靠推断。</p>
                ) : null}
              </article>
            ))}
          </section>
        ) : null}
      </main>
    </div>
  );
}
