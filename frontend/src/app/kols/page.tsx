"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Activity, ArrowUpRight, BellRing, Search, UsersRound } from "lucide-react";
import { AppLayout } from "@/components/AppLayout";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { CollectorHealthCard } from "@/components/CollectorHealthCard";
import { KolAvatar } from "@/components/KolAvatar";
import { LoadingState } from "@/components/LoadingState";
import { PlatformMark } from "@/components/PlatformMark";
import { StanceSummary } from "@/components/StanceSummary";
import { StatCard } from "@/components/StatCard";
import { useMarketData } from "@/lib/useMarketData";
import type { Kol, Signal } from "@/lib/types";

function formatRelativeTime(value?: string) {
  if (!value) return "暂无更新";
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return value;
  const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60000));
  if (minutes < 60) return `${Math.max(1, minutes)} 分钟前`;
  const hours = Math.floor(minutes / 60);
  return hours < 24 ? `${hours} 小时前` : `${Math.floor(hours / 24)} 天前`;
}

interface KolDirectoryEntry {
  kol: Kol;
  signals: Signal[];
}

export default function KolsPage() {
  const router = useRouter();
  const { signals, kols, assets, collectorHealth, loading, error, reload } = useMarketData();
  const [query, setQuery] = useState("");
  const [platform, setPlatform] = useState("");
  const [globalSymbol, setGlobalSymbol] = useState("");

  const platforms = useMemo(
    () => Array.from(new Set(signals.map((signal) => signal.platform).filter(Boolean))).sort(),
    [signals],
  );

  const entries = useMemo<KolDirectoryEntry[]>(() => {
    const directory = new Map<string, KolDirectoryEntry>();
    kols.forEach((kol) => directory.set(kol.id, { kol, signals: [] }));
    signals.forEach((signal) => {
      const existing = directory.get(signal.kol.id);
      if (existing) {
        existing.kol = {
          ...existing.kol,
          ...signal.kol,
          description: signal.kol.description || existing.kol.description,
          primaryMarket: signal.kol.primaryMarket || existing.kol.primaryMarket,
        };
        existing.signals.push(signal);
      } else {
        directory.set(signal.kol.id, { kol: signal.kol, signals: [signal] });
      }
    });
    return Array.from(directory.values()).sort((a, b) => b.signals.length - a.signals.length);
  }, [kols, signals]);

  const filteredEntries = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return entries.filter((entry) => {
      const matchesQuery =
        !keyword ||
        entry.kol.name.toLowerCase().includes(keyword) ||
        entry.kol.handle?.toLowerCase().includes(keyword) ||
        entry.kol.primaryMarket?.toLowerCase().includes(keyword);
      const matchesPlatform =
        !platform || entry.signals.some((signal) => signal.platform === platform);
      return matchesQuery && matchesPlatform;
    });
  }, [entries, platform, query]);

  const activeKols = entries.filter((entry) => entry.signals.length > 0).length;
  const actionable = signals.filter((signal) => signal.actionable).length;

  const rightPanel = (
    <aside className="entity-insight-panel" aria-label="KOL 洞察">
      <section className="insight-card">
        <div className="insight-title">
          <Activity size={16} aria-hidden="true" />
          <h2>活跃排行</h2>
        </div>
        <div className="rank-list">
          {entries.slice(0, 6).map((entry, index) => (
            <Link href={`/kols/${encodeURIComponent(entry.kol.id)}`} key={entry.kol.id}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <KolAvatar kol={entry.kol} platform={entry.signals[0]?.platform} size={28} />
              <strong>{entry.kol.name}</strong>
              <small>{entry.signals.length}</small>
            </Link>
          ))}
        </div>
      </section>

      <section className="insight-card">
        <div className="insight-title">
          <UsersRound size={16} aria-hidden="true" />
          <h2>平台覆盖</h2>
        </div>
        <div className="platform-coverage-list">
          {platforms.map((item) => (
            <div key={item}>
              <PlatformMark platform={item} withLabel />
              <strong>{signals.filter((signal) => signal.platform === item).length}</strong>
            </div>
          ))}
        </div>
      </section>

      <section className="insight-card subscription-cta">
        <BellRing size={18} aria-hidden="true" />
        <div>
          <strong>订阅新的 KOL</strong>
          <p>配置抓取间隔、分析 Prompt 和 ntfy 推送。</p>
        </div>
        <Link href="/admin">管理订阅 <ArrowUpRight size={14} aria-hidden="true" /></Link>
      </section>
      <CollectorHealthCard health={collectorHealth} />
    </aside>
  );

  return (
    <AppLayout
      title="KOL 情报源"
      eyebrow="Source Directory"
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
      <section className="stat-grid entity-stat-grid" aria-label="KOL 统计">
        <StatCard icon={UsersRound} label="监控 KOL" value={entries.length} detail="已配置情报源" />
        <StatCard icon={Activity} label="活跃来源" value={activeKols} detail="已有情报记录" tone="long" />
        <StatCard icon={BellRing} label="观点总数" value={signals.length} detail="当前数据窗口" />
        <StatCard icon={ArrowUpRight} label="可执行" value={actionable} detail="含标的与依据" tone="neutral" />
      </section>

      <section className="entity-directory">
        <div className="entity-toolbar">
          <div>
            <p className="terminal-label">Tracked Sources</p>
            <h2>全部 KOL</h2>
          </div>
          <label className="entity-search">
            <Search size={16} aria-hidden="true" />
            <input
              aria-label="搜索 KOL"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索名称、handle 或市场"
            />
          </label>
        </div>

        {loading ? (
          <LoadingState />
        ) : error ? (
          <ErrorState message={error} onRetry={reload} />
        ) : filteredEntries.length ? (
          <div className="kol-directory-list">
            {filteredEntries.map((entry) => {
              const latest = entry.signals[0];
              const sourcePlatform = latest?.platform || entry.kol.platform || "X";
              return (
                <article className="kol-directory-row" key={entry.kol.id}>
                  <div className="entity-primary">
                    <KolAvatar kol={entry.kol} platform={sourcePlatform} size={48} />
                    <div>
                      <div className="entity-name-line">
                        <Link href={`/kols/${encodeURIComponent(entry.kol.id)}`}>{entry.kol.name}</Link>
                        <PlatformMark platform={sourcePlatform} />
                      </div>
                      <span>@{(entry.kol.handle || entry.kol.name).replace(/^@/, "")}</span>
                      <p>{entry.kol.description || "金融交易观点与标的监控"}</p>
                    </div>
                  </div>
                  <div className="entity-market-cell">
                    <span>覆盖市场</span>
                    <strong>{entry.kol.primaryMarket || latest?.tags[0] || "综合"}</strong>
                  </div>
                  <div className="entity-stance-cell">
                    <span>观点分布</span>
                    <StanceSummary signals={entry.signals} compact />
                  </div>
                  <div className="entity-latest-cell">
                    <span>{formatRelativeTime(latest?.publishedAt)}</span>
                    <p>{latest?.summary || "等待首条情报"}</p>
                  </div>
                  <div className="entity-count-cell">
                    <strong>{entry.signals.length}</strong>
                    <span>条情报</span>
                  </div>
                  <Link className="entity-open-button" href={`/kols/${encodeURIComponent(entry.kol.id)}`} aria-label={`查看 ${entry.kol.name}`}>
                    <ArrowUpRight size={16} aria-hidden="true" />
                  </Link>
                </article>
              );
            })}
          </div>
        ) : (
          <EmptyState title="没有匹配的 KOL" description="调整名称或平台筛选后再查看。" />
        )}
      </section>
    </AppLayout>
  );
}
