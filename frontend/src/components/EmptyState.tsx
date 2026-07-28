"use client";

import { Inbox } from "lucide-react";

export function EmptyState({
  title = "暂无匹配情报",
  description = "调整筛选条件后再查看实时 KOL 信号。",
}: {
  title?: string;
  description?: string;
}) {
  return (
    <div className="state-panel state-panel-empty" role="status">
      <Inbox size={22} aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        <p>{description}</p>
      </div>
    </div>
  );
}
