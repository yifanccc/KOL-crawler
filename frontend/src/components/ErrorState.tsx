"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="state-panel state-panel-error" role="alert">
      <AlertTriangle size={22} aria-hidden="true" />
      <div>
        <strong>数据加载失败</strong>
        <p>{message}</p>
      </div>
      {onRetry ? (
        <button type="button" onClick={onRetry}>
          <RefreshCw size={15} aria-hidden="true" />
          重试
        </button>
      ) : null}
    </div>
  );
}
