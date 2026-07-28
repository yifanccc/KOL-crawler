"use client";

import type { Stance } from "@/lib/types";

const stanceMeta: Record<Stance, { label: string; className: string }> = {
  long: { label: "多", className: "stance-badge-long" },
  short: { label: "空", className: "stance-badge-short" },
  neutral: { label: "中性", className: "stance-badge-neutral" },
  unknown: { label: "不明确", className: "stance-badge-unknown" },
};

export function StanceBadge({ stance }: { stance: Stance }) {
  const meta = stanceMeta[stance];

  return <span className={`stance-badge ${meta.className}`}>{meta.label}</span>;
}
