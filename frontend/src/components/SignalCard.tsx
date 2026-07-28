"use client";

import Link from "next/link";
import { ArrowUpRight, ExternalLink, RadioTower } from "lucide-react";
import type { Signal } from "@/lib/types";

const stanceText = {
  long: "多",
  short: "空",
  neutral: "观望",
  unknown: "未知",
};

function formatTime(value?: string) {
  if (!value) return "时间未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatConfidence(value?: number) {
  if (typeof value !== "number") return null;
  const normalized = value <= 1 ? value * 100 : value;
  return Math.max(0, Math.min(100, Math.round(normalized)));
}

export function SignalCard({ signal }: { signal: Signal }) {
  const confidence = formatConfidence(signal.confidence);

  return (
    <article className={`signal-card stance-${signal.stance}`}>
      <div className="signal-line">
        <span className="stance-badge">{stanceText[signal.stance]}</span>
        <div className="signal-source">
          <Link href={`/kols/${encodeURIComponent(signal.kol.id)}`}>{signal.kol.name}</Link>
          <span>
            <RadioTower size={13} aria-hidden="true" />
            {signal.platform}
          </span>
        </div>
        <time dateTime={signal.publishedAt}>{formatTime(signal.publishedAt)}</time>
      </div>

      <p className="signal-summary">{signal.summary}</p>

      <div className="asset-row" aria-label="关联标的">
        {signal.assets.length ? (
          signal.assets.map((asset) => (
            <Link key={asset.symbol} href={`/assets/${encodeURIComponent(asset.symbol)}`}>
              {asset.symbol}
            </Link>
          ))
        ) : (
          <span>未识别标的</span>
        )}
      </div>

      <footer className="signal-footer">
        <div className="tag-row">
          {signal.actionable ? <span className="actionable">可执行</span> : <span>观察</span>}
          {confidence !== null ? <span>置信 {confidence}%</span> : null}
          {signal.tags.slice(0, 3).map((tag) => (
            <span key={tag}>{tag}</span>
          ))}
        </div>
        {signal.url ? (
          <a href={signal.url} target="_blank" rel="noreferrer" aria-label="打开原文">
            <ExternalLink size={16} aria-hidden="true" />
          </a>
        ) : (
          <ArrowUpRight size={16} aria-hidden="true" />
        )}
      </footer>
    </article>
  );
}
