"use client";

import { RotateCcw } from "lucide-react";
import type { DashboardFilters } from "@/lib/dashboardFilters";
import type { Asset, Kol } from "@/lib/types";

interface FilterBarProps {
  filters: DashboardFilters;
  kols: Kol[];
  assets: Asset[];
  tags: string[];
  platforms: string[];
  onChange: (filters: DashboardFilters) => void;
  onReset: () => void;
}

function patchFilters(filters: DashboardFilters, patch: Partial<DashboardFilters>) {
  return { ...filters, ...patch };
}

export function FilterBar({
  filters,
  kols,
  assets,
  tags,
  platforms,
  onChange,
  onReset,
}: FilterBarProps) {
  return (
    <section className="filter-bar" aria-label="情报筛选">
      <label>
        <span>KOL</span>
        <select
          value={filters.kolId}
          onChange={(event) => onChange(patchFilters(filters, { kolId: event.target.value }))}
        >
          <option value="">全部 KOL</option>
          {kols.map((kol) => (
            <option key={kol.id} value={kol.id}>
              {kol.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>平台</span>
        <select
          value={filters.platform}
          onChange={(event) => onChange(patchFilters(filters, { platform: event.target.value }))}
        >
          <option value="">全部</option>
          {platforms.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>观点</span>
        <select
          value={filters.stance}
          onChange={(event) => onChange(patchFilters(filters, { stance: event.target.value as DashboardFilters["stance"] }))}
        >
          <option value="">全部</option>
          <option value="long">多</option>
          <option value="short">空</option>
          <option value="neutral">中性</option>
          <option value="unknown">不明确</option>
        </select>
      </label>
      <label>
        <span>执行性</span>
        <select
          value={filters.actionableOnly ? "true" : ""}
          onChange={(event) =>
            onChange(
              patchFilters(filters, {
                actionableOnly: event.target.value === "true",
              }),
            )
          }
        >
          <option value="">全部</option>
          <option value="true">仅可执行</option>
        </select>
      </label>
      <label>
        <span>标的</span>
        <select
          value={filters.symbol}
          onChange={(event) => onChange(patchFilters(filters, { symbol: event.target.value }))}
        >
          <option value="">全部标的</option>
          {assets.map((asset) => (
            <option key={asset.id} value={asset.symbol.replace(/^\$/, "").toUpperCase()}>
              {asset.symbol.replace(/^\$/, "").toUpperCase()}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>标签</span>
        <select
          value={filters.tag}
          onChange={(event) => onChange(patchFilters(filters, { tag: event.target.value }))}
        >
          <option value="">全部标签</option>
          {tags.map((tag) => (
            <option key={tag} value={tag}>
              {tag}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>时间</span>
        <select
          value={filters.timeRange}
          onChange={(event) => onChange(patchFilters(filters, { timeRange: event.target.value }))}
        >
          <option value="all">全部</option>
          <option value="24h">24 小时</option>
          <option value="1h">1 小时</option>
          <option value="6h">6 小时</option>
          <option value="7d">7 天</option>
        </select>
      </label>
      <label>
        <span>重要性</span>
        <select
          value={filters.minImportance}
          onChange={(event) =>
            onChange(patchFilters(filters, { minImportance: Number(event.target.value) || 1 }))
          }
        >
          {[1, 2, 3, 4, 5].map((level) => (
            <option key={level} value={level}>
              {level}+
            </option>
          ))}
        </select>
      </label>
      <button type="button" className="ghost-button" onClick={onReset}>
        <RotateCcw size={14} aria-hidden="true" />
        重置
      </button>
    </section>
  );
}
