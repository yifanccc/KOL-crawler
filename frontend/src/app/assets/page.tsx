"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Activity, ArrowUpRight, BarChart3, Hash, Search, UsersRound } from "lucide-react";
import { AppLayout } from "@/components/AppLayout";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { StanceSummary } from "@/components/StanceSummary";
import { StatCard } from "@/components/StatCard";
import { useMarketData } from "@/lib/useMarketData";
import type { Asset, Signal } from "@/lib/types";

function normalizeSymbol(value: string) {
  return value.replace(/^\$/, "").toUpperCase();
}

function formatRelativeTime(value?: string) {
  if (!value) return "暂无更新";
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return value;
  const hours = Math.max(0, Math.floor((Date.now() - timestamp) / 3_600_000));
  if (hours < 1) return "1 小时内";
  return hours < 24 ? `${hours} 小时前` : `${Math.floor(hours / 24)} 天前`;
}

interface AssetDirectoryEntry {
  asset: Asset;
  signals: Signal[];
}

export default function AssetsPage() {
  const router = useRouter();
  const { signals, kols, assets, loading, error, reload } = useMarketData();
  const [query, setQuery] = useState("");
  const [platform, setPlatform] = useState("");
  const [market, setMarket] = useState("");
  const [globalSymbol, setGlobalSymbol] = useState("");

  const platforms = useMemo(
    () => Array.from(new Set(signals.map((signal) => signal.platform).filter(Boolean))).sort(),
    [signals],
  );

  const entries = useMemo<AssetDirectoryEntry[]>(() => {
    const directory = new Map<string, AssetDirectoryEntry>();
    assets.forEach((asset) => {
      directory.set(normalizeSymbol(asset.symbol), { asset, signals: [] });
    });
    signals.forEach((signal) => {
      signal.assets.forEach((signalAsset) => {
        const symbol = normalizeSymbol(signalAsset.symbol);
        const existing = directory.get(symbol);
        if (existing) {
          existing.signals.push(signal);
        } else {
          directory.set(symbol, {
            asset: { id: symbol, symbol, name: signalAsset.name || symbol },
            signals: [signal],
          });
        }
      });
    });
    return Array.from(directory.values()).sort((a, b) => b.signals.length - a.signals.length);
  }, [assets, signals]);

  const markets = useMemo(
    () => Array.from(new Set(entries.map((entry) => entry.asset.market).filter(Boolean) as string[])).sort(),
    [entries],
  );

  const filteredEntries = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return entries.filter((entry) => {
      const matchesQuery =
        !keyword ||
        entry.asset.symbol.toLowerCase().includes(keyword) ||
        entry.asset.name.toLowerCase().includes(keyword);
      const matchesMarket = !market || entry.asset.market === market;
      const matchesPlatform = !platform || entry.signals.some((signal) => signal.platform === platform);
      return matchesQuery && matchesMarket && matchesPlatform;
    });
  }, [entries, market, platform, query]);

  const mentionedAssets = entries.filter((entry) => entry.signals.length > 0).length;
  const bullishAssets = entries.filter((entry) => {
    const longs = entry.signals.filter((signal) => signal.stance === "long").length;
    const shorts = entry.signals.filter((signal) => signal.stance === "short").length;
    return longs > shorts;
  }).length;

  const rightPanel = (
    <aside className="entity-insight-panel" aria-label="标的洞察">
      <section className="insight-card">
        <div className="insight-title">
          <BarChart3 size={16} aria-hidden="true" />
          <h2>提及排行</h2>
        </div>
        <div className="asset-rank-list">
          {entries.slice(0, 8).map((entry, index) => (
            <Link href={`/assets/${encodeURIComponent(normalizeSymbol(entry.asset.symbol))}`} key={entry.asset.id}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <span className="symbol-badge">{normalizeSymbol(entry.asset.symbol)}</span>
              <strong>{entry.signals.length}</strong>
            </Link>
          ))}
        </div>
      </section>

      <section className="insight-card">
        <div className="insight-title">
          <Hash size={16} aria-hidden="true" />
          <h2>市场覆盖</h2>
        </div>
        <div className="market-coverage-list">
          {markets.map((item) => (
            <div key={item}>
              <span>{item}</span>
              <strong>{entries.filter((entry) => entry.asset.market === item).length}</strong>
            </div>
          ))}
        </div>
      </section>

      <section className="insight-card">
        <div className="insight-title">
          <UsersRound size={16} aria-hidden="true" />
          <h2>覆盖 KOL</h2>
        </div>
        <div className="market-coverage-list">
          <div><span>活跃来源</span><strong>{kols.length}</strong></div>
          <div><span>平台数量</span><strong>{platforms.length}</strong></div>
          <div><span>观点总数</span><strong>{signals.length}</strong></div>
        </div>
      </section>
    </aside>
  );

  return (
    <AppLayout
      title="标的情报库"
      eyebrow="Asset Intelligence"
      symbol={globalSymbol}
      platform={platform}
      platforms={platforms}
      suggestions={entries.map((entry) => normalizeSymbol(entry.asset.symbol))}
      onSymbolChange={(symbol) => {
        const normalized = normalizeSymbol(symbol.trim());
        setGlobalSymbol(normalized);
        if (normalized) router.push(`/assets/${encodeURIComponent(normalized)}`);
      }}
      onPlatformChange={setPlatform}
      rightPanel={rightPanel}
    >
      <section className="stat-grid entity-stat-grid" aria-label="标的统计">
        <StatCard icon={Hash} label="跟踪标的" value={entries.length} detail="跨市场资产库" />
        <StatCard icon={Activity} label="有情报标的" value={mentionedAssets} detail="至少被提及一次" tone="long" />
        <StatCard icon={ArrowUpRight} label="偏多标的" value={bullishAssets} detail="多方观点占优" tone="long" />
        <StatCard icon={BarChart3} label="覆盖市场" value={markets.length} detail="美股 / 加密 / A股" tone="neutral" />
      </section>

      <section className="entity-directory">
        <div className="entity-toolbar">
          <div>
            <p className="terminal-label">Tracked Universe</p>
            <h2>全部标的</h2>
          </div>
          <div className="entity-toolbar-controls">
            <label className="entity-search">
              <Search size={16} aria-hidden="true" />
              <input
                aria-label="搜索标的"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索代码或名称"
              />
            </label>
            <select aria-label="市场筛选" value={market} onChange={(event) => setMarket(event.target.value)}>
              <option value="">全部市场</option>
              {markets.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </div>
        </div>

        {loading ? (
          <LoadingState />
        ) : error ? (
          <ErrorState message={error} onRetry={reload} />
        ) : filteredEntries.length ? (
          <div className="asset-directory-list">
            {filteredEntries.map((entry) => {
              const latest = entry.signals[0];
              const kolCount = new Set(entry.signals.map((signal) => signal.kol.id)).size;
              return (
                <article className="asset-directory-row" key={entry.asset.id}>
                  <div className="asset-symbol-cell">
                    <Link href={`/assets/${encodeURIComponent(normalizeSymbol(entry.asset.symbol))}`}>
                      {normalizeSymbol(entry.asset.symbol)}
                    </Link>
                    <div>
                      <strong>{entry.asset.name || entry.asset.symbol}</strong>
                      <span>{entry.asset.market || "未分类"} · {entry.asset.assetType || "asset"}</span>
                    </div>
                  </div>
                  <div className="entity-stance-cell">
                    <span>观点分布</span>
                    <StanceSummary signals={entry.signals} compact />
                  </div>
                  <div className="asset-kol-cell">
                    <span>活跃 KOL</span>
                    <strong>{kolCount}</strong>
                  </div>
                  <div className="entity-latest-cell asset-latest-cell">
                    <span>{formatRelativeTime(latest?.publishedAt)}</span>
                    <p>{latest?.summary || "等待首条标的情报"}</p>
                  </div>
                  <div className="entity-count-cell">
                    <strong>{entry.signals.length}</strong>
                    <span>次提及</span>
                  </div>
                  <Link className="entity-open-button" href={`/assets/${encodeURIComponent(normalizeSymbol(entry.asset.symbol))}`} aria-label={`查看 ${entry.asset.symbol}`}>
                    <ArrowUpRight size={16} aria-hidden="true" />
                  </Link>
                </article>
              );
            })}
          </div>
        ) : (
          <EmptyState title="没有匹配标的" description="调整代码、市场或平台筛选后再查看。" />
        )}
      </section>
    </AppLayout>
  );
}
