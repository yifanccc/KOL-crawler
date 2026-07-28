"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Activity, ArrowLeft, BellRing, ExternalLink, Target, TrendingUp } from "lucide-react";
import { AppLayout } from "@/components/AppLayout";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { CollectorHealthCard } from "@/components/CollectorHealthCard";
import { FeedCard } from "@/components/FeedCard";
import { KolAvatar } from "@/components/KolAvatar";
import { LoadingState } from "@/components/LoadingState";
import { PlatformMark } from "@/components/PlatformMark";
import { StanceSummary } from "@/components/StanceSummary";
import { StatCard } from "@/components/StatCard";
import { SymbolBadge } from "@/components/SymbolBadge";
import { TagBadge } from "@/components/TagBadge";
import { useMarketData } from "@/lib/useMarketData";

function topEntries(values: string[], limit: number, normalize = true) {
  const counts = values.reduce<Record<string, number>>((acc, value) => {
    const key = normalize ? value.replace(/^\$/, "").toUpperCase() : value;
    if (key) acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
  return Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, limit);
}

export default function KolPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const kolId = decodeURIComponent(params.id);
  const { signals, kols, assets, collectorHealth, loading, error, reload } = useMarketData();
  const [platform, setPlatform] = useState("");
  const [selectedTag, setSelectedTag] = useState("");
  const [globalSymbol, setGlobalSymbol] = useState("");

  const kolSignals = useMemo(
    () => signals.filter((signal) => signal.kol.id === kolId),
    [kolId, signals],
  );
  const kol = kolSignals[0]?.kol || kols.find((item) => item.id === kolId);
  const platforms = Array.from(new Set(kolSignals.map((signal) => signal.platform))).sort();
  const visibleSignals = kolSignals.filter((signal) => {
    if (platform && signal.platform !== platform) return false;
    if (selectedTag && !signal.tags.includes(selectedTag)) return false;
    return true;
  });
  const actionable = kolSignals.filter((signal) => signal.actionable).length;
  const longCount = kolSignals.filter((signal) => signal.stance === "long").length;
  const topAssets = topEntries(
    kolSignals.flatMap((signal) => signal.assets.map((asset) => asset.symbol)),
    8,
  );
  const topTags = topEntries(kolSignals.flatMap((signal) => signal.tags), 8, false);
  const sourcePlatform = platforms[0] || kol?.platform || "X";

  const rightPanel = (
    <aside className="entity-insight-panel" aria-label="KOL 画像">
      <section className="insight-card">
        <div className="insight-title">
          <TrendingUp size={16} aria-hidden="true" />
          <h2>观点结构</h2>
        </div>
        <StanceSummary signals={kolSignals} />
      </section>

      <section className="insight-card">
        <div className="insight-title">
          <Target size={16} aria-hidden="true" />
          <h2>高频标的</h2>
        </div>
        <div className="weighted-badge-list">
          {topAssets.map(([symbol, count]) => (
            <div key={symbol}>
              <SymbolBadge symbol={symbol} />
              <span>{count}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="insight-card" id="tags">
        <div className="insight-title">
          <Activity size={16} aria-hidden="true" />
          <h2>内容标签</h2>
        </div>
        <div className="tag-cloud">
          {topTags.map(([tag]) => <TagBadge key={tag} tag={tag} onSelect={setSelectedTag} />)}
        </div>
      </section>

      <section className="insight-card prompt-profile">
        <span>分析侧写</span>
        <p>优先提取方向、标的、催化依据、时间周期与风险。对供应链、AI 基础设施和事件驱动内容提高重要性。</p>
      </section>
      <CollectorHealthCard health={collectorHealth} />
    </aside>
  );

  return (
    <AppLayout
      title={kol ? `${kol.name} 情报档案` : "KOL 情报档案"}
      eyebrow="KOL Intelligence Profile"
      symbol={globalSymbol}
      platform={platform}
      platforms={platforms}
      suggestions={assets.map((asset) => asset.symbol)}
      onSymbolChange={(symbol) => {
        const normalized = symbol.trim().replace(/^\$/, "").toUpperCase();
        setGlobalSymbol(normalized);
        if (normalized) router.push(`/assets/${encodeURIComponent(normalized)}`);
      }}
      onPlatformChange={setPlatform}
      rightPanel={rightPanel}
    >
      {loading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : !kol ? (
        <EmptyState title="找不到该 KOL" description="该情报源可能已被移除。" />
      ) : (
        <>
          <section className="entity-hero kol-profile-hero">
            <div className="entity-hero-main">
              <KolAvatar kol={kol} platform={sourcePlatform} size={76} />
              <div>
                <Link className="back-link" href="/kols"><ArrowLeft size={14} aria-hidden="true" />KOL 列表</Link>
                <div className="entity-title-line">
                  <h2>{kol.name}</h2>
                  <PlatformMark platform={sourcePlatform} withLabel />
                </div>
                <p className="entity-handle">@{(kol.handle || kol.name).replace(/^@/, "")}</p>
                <p className="entity-description">{kol.description || "金融交易观点、行业趋势与标的情报跟踪。"}</p>
                <div className="entity-hero-tags">
                  <span>{kol.primaryMarket || "综合市场"}</span>
                  <span className="live-status"><i />分钟级监控</span>
                </div>
              </div>
            </div>
            <div className="entity-hero-actions">
              <a href={`https://x.com/${encodeURIComponent((kol.handle || kol.name).replace(/^@/, ""))}`} target="_blank" rel="noreferrer">
                <PlatformMark platform="X" />查看主页<ExternalLink size={14} aria-hidden="true" />
              </a>
              <Link href="/admin"><BellRing size={15} aria-hidden="true" />订阅设置</Link>
            </div>
          </section>

          <section className="stat-grid entity-stat-grid" aria-label="KOL 指标">
            <StatCard icon={Activity} label="观点总数" value={kolSignals.length} detail="当前数据窗口" />
            <StatCard icon={BellRing} label="可执行" value={actionable} detail="包含标的与依据" tone="long" />
            <StatCard icon={TrendingUp} label="偏多观点" value={longCount} detail="已识别方向" tone="long" />
            <StatCard icon={Target} label="覆盖标的" value={topAssets.length} detail="高频资产范围" tone="neutral" />
          </section>

          <section className="feed-section" aria-live="polite">
            <div className="section-heading">
              <div>
                <p className="terminal-label">Latest Intelligence</p>
                <h2>最新观点</h2>
              </div>
              <div className="section-heading-actions">
                {selectedTag ? (
                  <button type="button" onClick={() => setSelectedTag("")}>标签：{selectedTag} ×</button>
                ) : null}
                <span>{visibleSignals.length} items</span>
              </div>
            </div>
            {visibleSignals.length ? (
              <div className="feed-list">
                {visibleSignals.map((signal) => (
                  <FeedCard
                    key={signal.id}
                    signal={signal}
                    onSymbolSelect={(symbol) => router.push(`/assets/${encodeURIComponent(symbol)}`)}
                    onTagSelect={setSelectedTag}
                  />
                ))}
              </div>
            ) : (
              <EmptyState title="没有匹配观点" description="清除标签或平台筛选后再查看。" />
            )}
          </section>
        </>
      )}
    </AppLayout>
  );
}
