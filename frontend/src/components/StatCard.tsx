"use client";

import type { LucideIcon } from "lucide-react";

interface StatCardProps {
  label: string;
  value: string | number;
  detail?: string;
  tone?: "cyan" | "long" | "short" | "neutral";
  icon: LucideIcon;
  active?: boolean;
  onClick?: () => void;
}

export function StatCard({
  label,
  value,
  detail,
  tone = "cyan",
  icon: Icon,
  active = false,
  onClick,
}: StatCardProps) {
  const className = `stat-card stat-card-${tone}${active ? " stat-card-active" : ""}`;
  const content = (
    <>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
      <Icon size={18} aria-hidden="true" />
      {detail ? <p>{detail}</p> : null}
    </>
  );

  return onClick ? (
    <button
      type="button"
      className={`${className} stat-card-interactive`}
      aria-pressed={active}
      onClick={onClick}
    >
      {content}
    </button>
  ) : (
    <article className={className}>{content}</article>
  );
}
