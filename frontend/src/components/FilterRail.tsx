"use client";

import type { Asset, Kol } from "@/lib/types";

interface FilterRailProps {
  kols: Kol[];
  assets: Asset[];
  stance: string;
  actionableOnly: boolean;
  selectedKol?: string;
  selectedSymbol?: string;
  onStanceChange: (value: string) => void;
  onActionableChange: (value: boolean) => void;
  onKolChange?: (value: string) => void;
  onSymbolChange?: (value: string) => void;
}

export function FilterRail({
  kols,
  assets,
  stance,
  actionableOnly,
  selectedKol = "",
  selectedSymbol = "",
  onStanceChange,
  onActionableChange,
  onKolChange,
  onSymbolChange,
}: FilterRailProps) {
  return (
    <aside className="filter-rail" aria-label="信号筛选">
      <div className="filter-block">
        <span className="filter-label">方向</span>
        <div className="segmented" role="group" aria-label="方向筛选">
          {[
            ["", "全部"],
            ["long", "多"],
            ["short", "空"],
            ["neutral", "观望"],
          ].map(([value, label]) => (
            <button
              key={value || "all"}
              className={stance === value ? "active" : ""}
              type="button"
              onClick={() => onStanceChange(value)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <label className="toggle-row">
        <input
          type="checkbox"
          checked={actionableOnly}
          onChange={(event) => onActionableChange(event.target.checked)}
        />
        只看可执行
      </label>

      {onKolChange ? (
        <label className="filter-block">
          <span className="filter-label">KOL</span>
          <select value={selectedKol} onChange={(event) => onKolChange(event.target.value)}>
            <option value="">全部 KOL</option>
            {kols.map((kol) => (
              <option key={kol.id} value={kol.id}>
                {kol.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      {onSymbolChange ? (
        <label className="filter-block">
          <span className="filter-label">标的</span>
          <select value={selectedSymbol} onChange={(event) => onSymbolChange(event.target.value)}>
            <option value="">全部标的</option>
            {assets.map((asset) => (
              <option key={asset.id} value={asset.symbol}>
                {asset.symbol}
              </option>
            ))}
          </select>
        </label>
      ) : null}
    </aside>
  );
}
