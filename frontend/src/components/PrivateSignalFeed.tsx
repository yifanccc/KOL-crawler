"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";

import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { FeedCard } from "@/components/FeedCard";
import { FilterBar } from "@/components/FilterBar";
import { LoadingState } from "@/components/LoadingState";
import { Sidebar } from "@/components/Sidebar";
import { fetchPrivateSignalPage } from "@/lib/api";
import {
  defaultDashboardFilters,
  type DashboardFilters,
} from "@/lib/dashboardFilters";
import {
  appendSignalPage,
  hasMoreSignals,
  loadedSignalsLabel,
  nextSignalOffset,
  refreshSignalPage,
  SIGNAL_BATCH_SIZE,
} from "@/lib/signalFeed";
import type { Asset, Kol, SignalPage, SignalQuery } from "@/lib/types";


const emptyPage: SignalPage = {
  items: [],
  total: 0,
  overallTotal: 0,
  actionableTotal: 0,
  limit: SIGNAL_BATCH_SIZE,
  offset: 0,
};

function queryFor(filters: DashboardFilters, offset: number): SignalQuery {
  return {
    kolId: filters.kolId || undefined,
    platform: filters.platform || undefined,
    symbol: filters.symbol || undefined,
    tag: filters.tag || undefined,
    stance: filters.stance || undefined,
    actionable: filters.actionableOnly ? true : undefined,
    timeRange: filters.timeRange,
    minImportance: filters.minImportance,
    limit: SIGNAL_BATCH_SIZE,
    offset,
  };
}

export function PrivateSignalFeed() {
  const [page, setPage] = useState<SignalPage>(emptyPage);
  const [filters, setFilters] = useState<DashboardFilters>(defaultDashboardFilters);
  const [nextOffset, setNextOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [loadMoreError, setLoadMoreError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const hasLoadedRef = useRef(false);
  const requestVersionRef = useRef(0);

  useEffect(() => {
    let active = true;
    const blocking = !hasLoadedRef.current;
    const requestVersion = requestVersionRef.current;
    if (blocking) {
      setLoading(true);
      setError("");
    }
    fetchPrivateSignalPage(queryFor(filters, 0))
      .then((nextPage) => {
        if (!active || requestVersion !== requestVersionRef.current) return;
        setPage((current) =>
          blocking ? nextPage : refreshSignalPage(current, nextPage),
        );
        if (blocking) setNextOffset(nextSignalOffset(nextPage));
        hasLoadedRef.current = true;
        setError("");
        setLoadMoreError("");
      })
      .catch((reason: unknown) => {
        if (
          active &&
          blocking &&
          requestVersion === requestVersionRef.current
        ) {
          setError(reason instanceof Error ? reason.message : "私有信号读取失败");
        }
      })
      .finally(() => {
        if (
          active &&
          blocking &&
          requestVersion === requestVersionRef.current
        ) {
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [filters, reloadKey]);

  const reload = useCallback(() => {
    requestVersionRef.current += 1;
    setLoadingMore(false);
    setLoadMoreError("");
    setReloadKey((value) => value + 1);
  }, []);

  useEffect(() => {
    const timer = window.setInterval(reload, 60_000);
    return () => window.clearInterval(timer);
  }, [reload]);

  const filterOptions = useMemo(() => {
    const kolMap = new Map<string, Kol>();
    const assetMap = new Map<string, Asset>();
    const platforms = new Set<string>();
    const tags = new Set<string>();
    page.items.forEach((signal) => {
      kolMap.set(signal.kol.id, signal.kol);
      platforms.add(signal.platform);
      signal.tags.forEach((tag) => tags.add(tag));
      signal.assets.forEach((asset) => {
        const symbol = asset.symbol.replace(/^\$/, "").toUpperCase();
        assetMap.set(symbol, { id: symbol, symbol, name: asset.name || symbol });
      });
    });
    return {
      kols: Array.from(kolMap.values()),
      assets: Array.from(assetMap.values()),
      platforms: Array.from(platforms).sort(),
      tags: Array.from(tags).sort(),
    };
  }, [page.items]);

  function applyFilters(nextFilters: DashboardFilters) {
    requestVersionRef.current += 1;
    hasLoadedRef.current = false;
    setPage(emptyPage);
    setNextOffset(0);
    setLoading(true);
    setLoadingMore(false);
    setError("");
    setLoadMoreError("");
    setFilters(nextFilters);
  }

  async function loadMore() {
    if (loadingMore || !hasMoreSignals(nextOffset, page.total)) return;
    const requestVersion = requestVersionRef.current;
    setLoadingMore(true);
    setLoadMoreError("");
    try {
      const nextPage = await fetchPrivateSignalPage(queryFor(filters, nextOffset));
      if (requestVersion !== requestVersionRef.current) return;
      const appended = appendSignalPage(page, nextPage);
      setPage(appended.page);
      setNextOffset(appended.nextOffset);
    } catch (reason) {
      if (requestVersion === requestVersionRef.current) {
        setLoadMoreError(reason instanceof Error ? reason.message : "下一批数据加载失败");
      }
    } finally {
      if (requestVersion === requestVersionRef.current) setLoadingMore(false);
    }
  }

  const hasMore = hasMoreSignals(nextOffset, page.total);

  return (
    <div className="dashboard-shell">
      <Sidebar />
      <main className="positions-stage private-signal-shell">
        <header className="positions-header private-signal-header">
          <div>
            <p className="eyebrow">Private Trade Feed</p>
            <h1>成交变化</h1>
            <p className="private-signal-description">
              交易事件来自只读成交记录；持仓为推测值，不代表交易所实时持仓
            </p>
          </div>
          <button
            type="button"
            className="settings-new-button"
            disabled={loading}
            onClick={reload}
          >
            <RefreshCw size={15} aria-hidden="true" />刷新
          </button>
        </header>

        <nav className="positions-tabs" aria-label="持仓监控子页面">
          <Link href="/positions">当前持仓</Link>
          <Link className="active" href="/positions/history">成交变化</Link>
        </nav>

        <FilterBar
        filters={filters}
        kols={filterOptions.kols}
        assets={filterOptions.assets}
        tags={filterOptions.tags}
        platforms={filterOptions.platforms}
        onChange={applyFilters}
        onReset={() => applyFilters(defaultDashboardFilters)}
        />

        <section className="feed-section" aria-live="polite">
        <div className="section-heading feed-section-heading">
          <div>
            <p className="terminal-label">Binance Copy</p>
            <h2>成交记录与推测持仓变化</h2>
          </div>
          <div className="section-heading-actions">
            <span>{loadedSignalsLabel(page.items.length, page.total)}</span>
          </div>
        </div>

        {loading ? <LoadingState /> : null}
        {!loading && error ? (
          <ErrorState message={error} onRetry={reload} />
        ) : null}
        {!loading && !error && page.items.length === 0 ? (
          <EmptyState
            title="暂无私有交易信号"
            description="首轮抓取只建立基线；后续检测到新成交记录后会显示在这里。"
          />
        ) : null}
        {!loading && !error && page.items.length > 0 ? (
          <div className="feed-list">
            {page.items.map((signal) => (
              <FeedCard
                key={signal.id}
                signal={signal}
                kolHref={null}
                onSymbolSelect={(symbol) =>
                  applyFilters({ ...filters, symbol: symbol.replace(/^\$/, "").toUpperCase() })
                }
                onTagSelect={(tag) => applyFilters({ ...filters, tag })}
              />
            ))}
          </div>
        ) : null}

        {!loading && !error && page.items.length > 0 ? (
          <div className="feed-load-more">
            <span role="status">
              {loadMoreError
                ? `加载失败：${loadMoreError}`
                : loadingMore
                  ? "正在加载下一批…"
                  : hasMore
                    ? "还有更多私有交易事件"
                    : "已加载全部"}
            </span>
            {hasMore ? (
              <button type="button" disabled={loadingMore} onClick={() => void loadMore()}>
                {loadMoreError ? "重试" : "加载更多"}
              </button>
            ) : null}
          </div>
        ) : null}
        </section>
      </main>
    </div>
  );
}
