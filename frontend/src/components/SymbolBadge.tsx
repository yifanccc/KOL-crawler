"use client";

import Link from "next/link";

interface SymbolBadgeProps {
  symbol: string;
  name?: string;
  onSelect?: (symbol: string) => void;
}

function normalizeSymbol(symbol: string) {
  return symbol.replace(/^\$/, "").toUpperCase();
}

export function SymbolBadge({ symbol, name, onSelect }: SymbolBadgeProps) {
  const normalized = normalizeSymbol(symbol);
  const label = normalized || symbol;

  if (onSelect) {
    return (
      <button
        type="button"
        className="symbol-badge"
        title={name || `筛选 ${label}`}
        onClick={() => onSelect(label)}
      >
        {label}
      </button>
    );
  }

  return (
    <Link className="symbol-badge" href={`/assets/${encodeURIComponent(label)}`} title={name || label}>
      {label}
    </Link>
  );
}
