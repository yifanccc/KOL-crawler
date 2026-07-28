"use client";

import { Bell, Flame, Gauge, Tags } from "lucide-react";
import type { Signal, Stance } from "@/lib/types";
import { SymbolBadge } from "./SymbolBadge";
import { TagBadge } from "./TagBadge";

const stanceLabel: Record<Stance, string> = {
  long: "多",
  short: "空",
  neutral: "中性",
  unknown: "不明确",
};

function normalizeSymbol(symbol: string) {
  return symbol.replace(/^\$/, "").toUpperCase();
}

function topEntries(values: string[], limit: number) {
  const counts = values.reduce<Record<string, number>>((acc, value) => {
    if (!value) return acc;
    acc[value] = (acc[value] || 0) + 1;
    return acc;
  }, {});

  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit);
}

export function RightInsightPanel({
  signals,
  onSymbolSelect,
  onTagSelect,
}: {
  signals: Signal[];
  onSymbolSelect: (symbol: string) => void;
  onTagSelect: (tag: string) => void;
}) {
  const symbols = topEntries(
    signals.flatMap((signal) => signal.assets.map((asset) => normalizeSymbol(asset.symbol))),
    6,
  );
  const tags = topEntries(signals.flatMap((signal) => signal.tags), 8);
  const stanceCounts = {
    long: signals.filter((signal) => signal.stance === "long").length,
    short: signals.filter((signal) => signal.stance === "short").length,
    neutral: signals.filter((signal) => signal.stance === "neutral").length,
    unknown: signals.filter((signal) => signal.stance === "unknown").length,
  };
  const total = Math.max(1, signals.length);
  const latest = signals.slice(0, 4);

  return (
    <aside className="right-insight-panel" aria-label="市场洞察">
      <section className="insight-card">
        <div className="insight-title">
          <Flame size={16} aria-hidden="true" />
          <h2>热门标的</h2>
        </div>
        <div className="hot-symbol-list">
          {symbols.length ? (
            symbols.map(([symbol, count]) => (
              <div key={symbol}>
                <SymbolBadge symbol={symbol} onSelect={onSymbolSelect} />
                <span>{count}</span>
              </div>
            ))
          ) : (
            <p className="muted-text">暂无标的</p>
          )}
        </div>
      </section>

      <section className="insight-card">
        <div className="insight-title">
          <Gauge size={16} aria-hidden="true" />
          <h2>多空分布</h2>
        </div>
        <div className="stance-distribution">
          {(Object.entries(stanceCounts) as [Stance, number][]).map(([stance, count]) => (
            <div className={`distribution-row distribution-${stance}`} key={stance}>
              <span>{stanceLabel[stance]}</span>
              <div>
                <i style={{ width: `${Math.max(4, (count / total) * 100)}%` }} />
              </div>
              <strong>{count}</strong>
            </div>
          ))}
        </div>
      </section>

      <section className="insight-card">
        <div className="insight-title">
          <Tags size={16} aria-hidden="true" />
          <h2>高频标签</h2>
        </div>
        <div className="tag-cloud">
          {tags.length ? (
            tags.map(([tag]) => <TagBadge key={tag} tag={tag} onSelect={onTagSelect} />)
          ) : (
            <p className="muted-text">暂无标签</p>
          )}
        </div>
      </section>

      <section className="insight-card">
        <div className="insight-title">
          <Bell size={16} aria-hidden="true" />
          <h2>最新推送</h2>
        </div>
        <div className="push-list">
          {latest.length ? (
            latest.map((signal) => (
              <article key={signal.id}>
                <strong>{signal.kol.name}</strong>
                <span>{signal.summary}</span>
              </article>
            ))
          ) : (
            <p className="muted-text">暂无推送</p>
          )}
        </div>
      </section>
    </aside>
  );
}
