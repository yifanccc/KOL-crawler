"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Activity, BellRing, Flame, Scale } from "lucide-react";
import { AppLayout } from "@/components/AppLayout";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { FeedCard } from "@/components/FeedCard";
import { FilterBar } from "@/components/FilterBar";
import { LoadingState } from "@/components/LoadingState";
import { RightInsightPanel } from "@/components/RightInsightPanel";
import { StatCard } from "@/components/StatCard";
import { fetchAssets, fetchKols, fetchSignalPage } from "@/lib/api";
import {
  defaultDashboardFilters,
  toggleActionableOnly,
  type DashboardFilters,
} from "@/lib/dashboardFilters";
import { isBlockingRefresh, refreshErrorMessage } from "@/lib/refreshPolicy";
import {
  appendSignalPage,
  hasMoreSignals,
  loadedSignalsLabel,
  nextSignalOffset,
  refreshSignalPage,
  SIGNAL_BATCH_SIZE,
} from "@/lib/signalFeed";
import type { Asset, Kol, Signal, SignalPage } from "@/lib/types";

const defaultSymbols = ["BTC", "ETH", "SPX", "NDX", "NVDA", "AAPL", "TSLA", "000001"];
const emptySignalPage: SignalPage = {
  items: [],
  total: 0,
  overallTotal: 0,
  actionableTotal: 0,
  limit: SIGNAL_BATCH_SIZE,
  offset: 0,
};

function normalizeSymbol(symbol: string) {
  return symbol.replace(/^\$/, "").toUpperCase();
}

function normalizePlatform(platform: string) {
  return platform.trim().toUpperCase();
}

function mostActiveSymbol(signals: Signal[]) {
  const counts = signals.reduce<Record<string, number>>((acc, signal) => {
    signal.assets.forEach((asset) => {
      const symbol = normalizeSymbol(asset.symbol);
      if (symbol) acc[symbol] = (acc[symbol] || 0) + 1;
    });
    return acc;
  }, {});
  return Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] || "-";
}

export default function HomePage() {
  const [signalPage, setSignalPage] = useState<SignalPage>(emptySignalPage);
  const [kols, setKols] = useState<Kol[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [loadMoreError, setLoadMoreError] = useState("");
  const [filters, setFilters] = useState<DashboardFilters>(defaultDashboardFilters);
  const [nextOffset, setNextOffset] = useState(0);
  const hasLoadedRef = useRef(false);
  const loadingMoreRef = useRef(false);
  const loadMoreTargetRef = useRef<HTMLDivElement>(null);
  const requestVersionRef = useRef(0);
  const signals = signalPage.items;

  const signalQuery = useCallback(
    (offset: number) => ({
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
    }),
    [filters],
  );

  const loadDashboard = useCallback(async () => {
    const blocking = isBlockingRefresh(hasLoadedRef.current);
    const requestVersion = requestVersionRef.current;
    if (blocking) {
      setLoading(true);
      setError("");
    }
    try {
      const [nextSignalPage, nextKols, nextAssets] = await Promise.all([
        fetchSignalPage(signalQuery(0)),
        fetchKols(),
        fetchAssets(),
      ]);
      if (requestVersion !== requestVersionRef.current) return;
      setSignalPage((current) =>
        blocking ? nextSignalPage : refreshSignalPage(current, nextSignalPage),
      );
      if (blocking) {
        setNextOffset(nextSignalOffset(nextSignalPage));
      }
      setKols(nextKols);
      setAssets(nextAssets);
      hasLoadedRef.current = true;
      setError("");
      setLoadMoreError("");
    } catch (reason: unknown) {
      if (requestVersion !== requestVersionRef.current) return;
      const message = reason instanceof Error ? reason.message : "数据加载失败";
      setError(refreshErrorMessage(hasLoadedRef.current, message));
    } finally {
      if (blocking && requestVersion === requestVersionRef.current) {
        setLoading(false);
      }
    }
  }, [signalQuery]);

  const loadMore = useCallback(async () => {
    if (
      loadingMoreRef.current ||
      loading ||
      error ||
      !hasMoreSignals(nextOffset, signalPage.total)
    ) {
      return;
    }
    loadingMoreRef.current = true;
    setLoadingMore(true);
    setLoadMoreError("");
    const requestVersion = requestVersionRef.current;
    try {
      const nextPage = await fetchSignalPage(signalQuery(nextOffset));
      if (requestVersion !== requestVersionRef.current) return;
      setSignalPage((current) => appendSignalPage(current, nextPage).page);
      setNextOffset(nextSignalOffset(nextPage));
    } catch (reason: unknown) {
      if (requestVersion !== requestVersionRef.current) return;
      setLoadMoreError(reason instanceof Error ? reason.message : "下一批数据加载失败");
    } finally {
      if (requestVersion === requestVersionRef.current) {
        loadingMoreRef.current = false;
        setLoadingMore(false);
      }
    }
  }, [error, loading, nextOffset, signalPage.total, signalQuery]);

  useEffect(() => {
    void loadDashboard();
    const timer = window.setInterval(() => {
      void loadDashboard();
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [loadDashboard]);

  const hasMore = hasMoreSignals(nextOffset, signalPage.total);

  useEffect(() => {
    const target = loadMoreTargetRef.current;
    if (!target || !hasMore || loading || loadingMore || error) return;
    if (!("IntersectionObserver" in window)) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) void loadMore();
      },
      { rootMargin: "320px 0px" },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [error, hasMore, loadMore, loading, loadingMore]);

  const platforms = useMemo(
    () =>
      Array.from(
        new Set(
          [
            filters.platform,
            ...signals.map((signal) => signal.platform),
            ...kols.map((kol) => kol.platform || ""),
          ]
            .map(normalizePlatform)
            .filter(Boolean),
        ),
      ).sort(),
    [filters.platform, kols, signals],
  );

  const allTags = useMemo(
    () =>
      Array.from(
        new Set([filters.tag, ...signals.flatMap((signal) => signal.tags)].filter(Boolean)),
      ).sort(),
    [filters.tag, signals],
  );

  const symbolSuggestions = useMemo(() => {
    const fromAssets = assets.map((asset) => normalizeSymbol(asset.symbol));
    const fromSignals = signals.flatMap((signal) =>
      signal.assets.map((asset) => normalizeSymbol(asset.symbol)),
    );
    return Array.from(new Set([...defaultSymbols, ...fromAssets, ...fromSignals].filter(Boolean))).slice(0, 24);
  }, [assets, signals]);

  const longCount = signals.filter((signal) => signal.stance === "long").length;
  const shortCount = signals.filter((signal) => signal.stance === "short").length;
  const activeSymbol = mostActiveSymbol(signals);

  function applyFilters(nextFilters: DashboardFilters) {
    requestVersionRef.current += 1;
    hasLoadedRef.current = false;
    loadingMoreRef.current = false;
    setSignalPage(emptySignalPage);
    setNextOffset(0);
    setLoading(true);
    setLoadingMore(false);
    setLoadMoreError("");
    setError("");
    setFilters(nextFilters);
  }

  function selectSymbol(symbol: string) {
    applyFilters({ ...filters, symbol: normalizeSymbol(symbol) });
  }

  function selectTag(tag: string) {
    applyFilters({ ...filters, tag });
  }

  const feedContent = loading ? (
    <LoadingState />
  ) : error ? (
    <ErrorState message={error} onRetry={loadDashboard} />
  ) : signals.length ? (
    <div className="feed-list">
      {signals.map((signal) => (
        <FeedCard
          key={signal.id}
          signal={signal}
          onSymbolSelect={selectSymbol}
          onTagSelect={selectTag}
        />
      ))}
    </div>
  ) : (
    <EmptyState />
  );

  return (
    <AppLayout
      symbol={filters.symbol}
      platform={filters.platform}
      platforms={platforms}
      suggestions={symbolSuggestions}
      onSymbolChange={selectSymbol}
      onPlatformChange={(platform) => applyFilters({ ...filters, platform })}
      rightPanel={
        <RightInsightPanel
          signals={signals}
          onSymbolSelect={selectSymbol}
          onTagSelect={selectTag}
        />
      }
    >
      <section className="stat-grid" aria-label="市场统计">
        <StatCard
          icon={Activity}
          label="实时情报"
          value={signalPage.total}
          detail={`${signalPage.overallTotal} 条总样本`}
        />
        <StatCard
          icon={BellRing}
          label="可执行"
          value={signalPage.actionableTotal}
          detail={filters.actionableOnly ? "正在仅显示可执行信号" : "观点 + 标的 + 依据"}
          tone="long"
          active={filters.actionableOnly}
          onClick={() => applyFilters(toggleActionableOnly(filters))}
        />
        <StatCard icon={Flame} label="热门标的" value={activeSymbol} detail="当前筛选内最高频" />
        <StatCard
          icon={Scale}
          label="多空比"
          value={`${longCount}:${shortCount}`}
          detail="多 / 空"
          tone={shortCount > longCount ? "short" : "neutral"}
        />
      </section>

      <FilterBar
        filters={filters}
        kols={kols}
        assets={assets}
        tags={allTags}
        platforms={platforms}
        onChange={applyFilters}
        onReset={() => applyFilters(defaultDashboardFilters)}
      />

      <section className="feed-section" aria-live="polite">
        <div className="section-heading feed-section-heading">
          <div>
            <p className="terminal-label">Live Feed</p>
            <h2>KOL 观点卡片</h2>
          </div>
          <div className="section-heading-actions">
            <span>{loadedSignalsLabel(signals.length, signalPage.total)}</span>
          </div>
        </div>
        {feedContent}
        {!loading && !error && signals.length > 0 ? (
          <div ref={loadMoreTargetRef} className="feed-load-more">
            <span role="status">
              {loadMoreError
                ? `加载失败：${loadMoreError}`
                : loadingMore
                  ? "正在加载下一批…"
                  : hasMore
                    ? "继续下滑自动加载"
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
    </AppLayout>
  );
}
