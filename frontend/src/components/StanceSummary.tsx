"use client";

import type { Signal } from "@/lib/types";

export function StanceSummary({ signals, compact = false }: { signals: Signal[]; compact?: boolean }) {
  const long = signals.filter((signal) => signal.stance === "long").length;
  const short = signals.filter((signal) => signal.stance === "short").length;
  const neutral = signals.filter((signal) => signal.stance === "neutral").length;
  const unknown = signals.length - long - short - neutral;
  const total = Math.max(1, signals.length);

  return (
    <div className={`stance-summary ${compact ? "stance-summary-compact" : ""}`} aria-label="观点分布">
      <div className="stance-summary-track" aria-hidden="true">
        {long ? <i className="long" style={{ width: `${(long / total) * 100}%` }} /> : null}
        {short ? <i className="short" style={{ width: `${(short / total) * 100}%` }} /> : null}
        {neutral ? <i className="neutral" style={{ width: `${(neutral / total) * 100}%` }} /> : null}
        {unknown ? <i className="unknown" style={{ width: `${(unknown / total) * 100}%` }} /> : null}
      </div>
      <div className="stance-summary-labels">
        <span><i className="long" />多 {long}</span>
        <span><i className="short" />空 {short}</span>
        {!compact ? <span><i className="neutral" />中性 {neutral}</span> : null}
      </div>
    </div>
  );
}
