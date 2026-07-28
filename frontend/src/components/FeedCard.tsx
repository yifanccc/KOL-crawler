"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronDown, ExternalLink, Star } from "lucide-react";
import type { Signal } from "@/lib/types";
import { KolAvatar } from "./KolAvatar";
import { PlatformMark } from "./PlatformMark";
import { StanceBadge } from "./StanceBadge";
import { SymbolBadge } from "./SymbolBadge";
import { TagBadge } from "./TagBadge";

function formatRelativeTime(value?: string) {
  if (!value) return "时间未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const diffMinutes = Math.max(0, Math.floor((Date.now() - date.getTime()) / 60000));
  if (diffMinutes < 1) return "刚刚";
  if (diffMinutes < 60) return `${diffMinutes}分钟前`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}小时前`;
  return `${Math.floor(diffHours / 24)}天前`;
}

function formatAbsoluteTime(value?: string) {
  if (!value) return undefined;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function FeedCard({
  signal,
  onSymbolSelect,
  onTagSelect,
}: {
  signal: Signal;
  onSymbolSelect: (symbol: string) => void;
  onTagSelect: (tag: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const importance = Math.max(1, Math.min(5, signal.importance));

  return (
    <article className={`feed-card feed-card-${signal.stance}`}>
      <header className="feed-card-header">
        <div className="feed-card-identity">
          <Link href={`/kols/${encodeURIComponent(signal.kol.id)}`} aria-label={`查看 ${signal.kol.name}`}>
            <KolAvatar kol={signal.kol} platform={signal.platform} size={34} />
          </Link>
          <div className="feed-card-source">
            <div>
              <Link href={`/kols/${encodeURIComponent(signal.kol.id)}`}>{signal.kol.name}</Link>
              {signal.kol.handle ? <span>@{signal.kol.handle.replace(/^@/, "")}</span> : null}
            </div>
            <div>
              <PlatformMark platform={signal.platform} />
              <time dateTime={signal.publishedAt} title={formatAbsoluteTime(signal.publishedAt)}>
                {formatRelativeTime(signal.publishedAt)}
              </time>
            </div>
          </div>
        </div>
        {signal.url ? (
          <a className="source-link" href={signal.url} target="_blank" rel="noreferrer">
            原文链接
            <ExternalLink size={14} aria-hidden="true" />
          </a>
        ) : null}
      </header>

      <div className="feed-card-meta">
        <StanceBadge stance={signal.stance} />
        <div className="symbol-row" aria-label="关联标的">
          {signal.assets.length ? (
            signal.assets.map((asset, index) => (
              <SymbolBadge
                key={`${asset.symbol}-${index}`}
                symbol={asset.symbol}
                name={asset.name}
                onSelect={onSymbolSelect}
              />
            ))
          ) : (
            <span className="muted-pill">未识别标的</span>
          )}
        </div>
        <div className="importance-meter" aria-label={`重要性 ${importance}/5`}>
          <span>重要性</span>
          {Array.from({ length: 5 }).map((_, index) => (
            <i className={index < importance ? "active" : ""} key={index} />
          ))}
          <strong>{importance}/5</strong>
        </div>
      </div>

      <section className="feed-summary">
        <span>中文摘要</span>
        <p>{signal.summary}</p>
      </section>

      <section className="evidence-block">
        <span>核心依据</span>
        <ol>
          {(signal.evidence.length ? signal.evidence : ["模型未抽取明确依据"]).map((item, index) => (
            <li key={`${item}-${index}`}>{item}</li>
          ))}
        </ol>
      </section>

      <div className="tag-row">
        {signal.actionable ? <TagBadge tag="可执行" onSelect={onTagSelect} /> : <TagBadge tag="观察" />}
        {signal.tags.slice(0, 5).map((tag) => (
          <TagBadge key={tag} tag={tag} onSelect={onTagSelect} />
        ))}
      </div>

      <section className="signal-guidance" aria-label="解读与风险">
        <div>
          <span>行动提示</span>
          <p>{signal.actionHint || "仅记录原文观点，需结合其他信息确认。"}</p>
        </div>
        <div>
          <span>风险提示</span>
          <p>{signal.riskWarning || "观点仅供信息参考，不构成投资建议。"}</p>
        </div>
      </section>

      <button
        type="button"
        className="expand-button"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        <ChevronDown size={15} aria-hidden="true" />
        {expanded ? "收起" : "展开"}
      </button>

      {expanded ? (
        <section className="expanded-intel">
          <div>
            <span>原文</span>
            <p>{signal.rawText || "暂无原文缓存"}</p>
          </div>
          <div>
            <span>中文翻译</span>
            <p>{signal.translation || signal.summary}</p>
          </div>
          <div className="model-row">
            <span>
              <Star size={13} aria-hidden="true" />
              模型置信度：{signal.modelConfidence || "未知"}
            </span>
            <span>prompt版本：{signal.promptVersion || "default-v1"}</span>
          </div>
        </section>
      ) : null}
    </article>
  );
}
