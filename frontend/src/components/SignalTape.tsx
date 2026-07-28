"use client";

import type { Signal } from "@/lib/types";
import { SignalCard } from "./SignalCard";

interface SignalTapeProps {
  title: string;
  eyebrow?: string;
  signals: Signal[];
  loading: boolean;
  error?: string;
  emptyText?: string;
}

export function SignalTape({ title, eyebrow, signals, loading, error, emptyText = "暂无匹配信号" }: SignalTapeProps) {
  return (
    <section className="signal-tape" aria-live="polite">
      <div className="tape-header">
        <div>
          {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
          <h1>{title}</h1>
        </div>
        <div className="tape-count">
          <strong>{signals.length}</strong>
          <span>signals</span>
        </div>
      </div>

      {loading ? (
        <div className="state-panel">正在加载交易纸带...</div>
      ) : error ? (
        <div className="state-panel error">{error}</div>
      ) : signals.length === 0 ? (
        <div className="state-panel">{emptyText}</div>
      ) : (
        <div className="tape-list">
          {signals.map((signal) => (
            <SignalCard key={signal.id} signal={signal} />
          ))}
        </div>
      )}
    </section>
  );
}
