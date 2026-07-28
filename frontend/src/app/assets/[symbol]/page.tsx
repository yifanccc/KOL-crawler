"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Activity, ArrowLeft, BarChart3, Hash, Target, UsersRound } from "lucide-react";
import { AppLayout } from "@/components/AppLayout";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { FeedCard } from "@/components/FeedCard";
import { KolAvatar } from "@/components/KolAvatar";
import { LoadingState } from "@/components/LoadingState";
import { PlatformMark } from "@/components/PlatformMark";
import { StanceSummary } from "@/components/StanceSummary";
import { StatCard } from "@/components/StatCard";
import { SymbolBadge } from "@/components/SymbolBadge";
import { TagBadge } from "@/components/TagBadge";
import { useMarketData } from "@/lib/useMarketData";

function normalizeSymbol(value: string) {
  return value.replace(/^\$/, "").toUpperCase();
}

function topEntries(values: string[], limit: number) {
  const counts = values.reduce<Record<string, number>>((acc, value) => {
    if (value) acc[value] = (acc[value] || 0) + 1;
    return acc;
  }, {});
  return Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, limit);
}

export default function AssetPage() {
  const params = useParams<{ symbol: string }>();
  const router = useRouter();
  const symbol = normalizeSymbol(decodeURIComponent(params.symbol));
  const { signals, kols, assets, loading, error, reload } = useMarketData();
  const [platform, setPlatform] = useState("");
  const [selectedTag, setSelectedTag] = useState("");
  const [globalSymbol, setGlobalSymbol] = useState(symbol);

  const assetSignals = useMemo(
    () => signals.filter((signal) => signal.assets.some((item) => normalizeSymbol(item.symbol) === symbol)),
    [signals, symbol],
  );
  const asset = assets.find((item) => normalizeSymbol(item.symbol) === symbol) || {
    id: symbol,
    symbol,
    name: symbol,
  };
  const platforms = Array.from(new Set(assetSignals.map((signal) => signal.platform))).sort();
  const visibleSignals = assetSignals.filter((signal) => {
    if (platform && signal.platform !== platform) return false;
    if (selectedTag && !signal.tags.includes(selectedTag)) return false;
    return true;
  });
  const actionable = assetSignals.filter((signal) => signal.actionable).length;
  const longCount = assetSignals.filter((signal) => signal.stance === "long").length;
  const shortCount = assetSignals.filter((signal) => signal.stance === "short").length;
  const kolEntries = topEntries(assetSignals.map((signal) => signal.kol.id), 6).map(([id, count]) => ({
    kol: kols.find((item) => item.id === id) || assetSignals.find((signal) => signal.kol.id === id)!.kol,
    count,
    platform: assetSignals.find((signal) => signal.kol.id === id)?.platform || "X",
  }));
  const topTags = topEntries(assetSignals.flatMap((signal) => signal.tags), 8);
  const relatedAssets = topEntries(
    assetSignals.flatMap((signal) =>
      signal.assets
        .map((item) => normalizeSymbol(item.symbol))
        .filter((item) => item !== symbol),
    ),
    8,
  );

  const rightPanel = (
    <aside className="entity-insight-panel" aria-label="标的画像">
      <section className="insight-card">
        <div className="insight-title">
          <BarChart3 size={16} aria-hidden="true" />
          <h2>观点结构</h2>
        </div>
        <StanceSummary signals={assetSignals} />
      </section>

      <section className="insight-card">
        <div className="insight-title">
          <UsersRound size={16} aria-hidden="true" />
          <h2>活跃 KOL</h2>
        </div>
        <div className="asset-kol-rank">
          {kolEntries.map((entry) => (
            <Link href={`/kols/${encodeURIComponent(entry.kol.id)}`} key={entry.kol.id}>
              <KolAvatar kol={entry.kol} platform={entry.platform} size={30} />
              <div><strong>{entry.kol.name}</strong><PlatformMark platform={entry.platform} /></div>
              <span>{entry.count}</span>
            </Link>
          ))}
        </div>
      </section>

      <section className="insight-card" id="tags">
        <div className="insight-title">
          <Activity size={16} aria-hidden="true" />
          <h2>高频标签</h2>
        </div>
        <div className="tag-cloud">
          {topTags.map(([tag]) => <TagBadge key={tag} tag={tag} onSelect={setSelectedTag} />)}
        </div>
      </section>

      <section className="insight-card">
        <div className="insight-title">
          <Target size={16} aria-hidden="true" />
          <h2>相关标的</h2>
        </div>
        <div className="weighted-badge-list">
          {relatedAssets.map(([item, count]) => (
            <div key={item}><SymbolBadge symbol={item} /><span>{count}</span></div>
          ))}
        </div>
      </section>
    </aside>
  );

  return (
    <AppLayout
      title={`${symbol} 标的档案`}
      eyebrow="Asset Intelligence Profile"
      symbol={globalSymbol}
      platform={platform}
      platforms={platforms}
      suggestions={assets.map((item) => normalizeSymbol(item.symbol))}
      onSymbolChange={(value) => {
        const normalized = normalizeSymbol(value.trim());
        setGlobalSymbol(normalized);
        if (normalized && normalized !== symbol) router.push(`/assets/${encodeURIComponent(normalized)}`);
      }}
      onPlatformChange={setPlatform}
      rightPanel={rightPanel}
    >
      {loading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : (
        <>
          <section className="entity-hero asset-profile-hero">
            <div className="entity-hero-main">
              <div className="asset-monogram">{symbol.slice(0, 4)}</div>
              <div>
                <Link className="back-link" href="/assets"><ArrowLeft size={14} aria-hidden="true" />标的库</Link>
                <div className="entity-title-line">
                  <h2>{symbol}</h2>
                  <span className="asset-market-badge">{asset.market || "未分类"}</span>
                </div>
                <p className="entity-description">{asset.name || symbol}</p>
                <div className="entity-hero-tags">
                  <span>{asset.assetType || "asset"}</span>
                  <span className="live-status"><i />实时跟踪</span>
                </div>
              </div>
            </div>
            <div className="asset-bias-summary">
              <span>当前倾向</span>
              <strong className={longCount > shortCount ? "bias-long" : shortCount > longCount ? "bias-short" : ""}>
                {longCount > shortCount ? "偏多" : shortCount > longCount ? "偏空" : "中性"}
              </strong>
              <small>{longCount} 多 / {shortCount} 空</small>
            </div>
          </section>

          <section className="stat-grid entity-stat-grid" aria-label="标的指标">
            <StatCard icon={Activity} label="提及次数" value={assetSignals.length} detail="当前情报窗口" />
            <StatCard icon={Target} label="可执行" value={actionable} detail="含方向与依据" tone="long" />
            <StatCard icon={UsersRound} label="活跃 KOL" value={kolEntries.length} detail="独立观点来源" tone="neutral" />
            <StatCard icon={BarChart3} label="多空比" value={`${longCount}:${shortCount}`} detail="多 / 空" tone={shortCount > longCount ? "short" : "long"} />
          </section>

          <section className="feed-section" aria-live="polite">
            <div className="section-heading">
              <div>
                <p className="terminal-label">Mention Timeline</p>
                <h2>相关情报</h2>
              </div>
              <div className="section-heading-actions">
                {selectedTag ? <button type="button" onClick={() => setSelectedTag("")}>标签：{selectedTag} ×</button> : null}
                <span>{visibleSignals.length} items</span>
              </div>
            </div>
            {visibleSignals.length ? (
              <div className="feed-list">
                {visibleSignals.map((signal) => (
                  <FeedCard
                    key={signal.id}
                    signal={signal}
                    onSymbolSelect={(nextSymbol) => router.push(`/assets/${encodeURIComponent(nextSymbol)}`)}
                    onTagSelect={setSelectedTag}
                  />
                ))}
              </div>
            ) : (
              <EmptyState title="暂无相关情报" description="该标的在当前筛选范围内没有匹配观点。" />
            )}
          </section>
        </>
      )}
    </AppLayout>
  );
}
