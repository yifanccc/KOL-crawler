import type { PositionSnapshot } from "./types";


const statusPriority: Record<PositionSnapshot["status"], number> = {
  UNKNOWN: 0,
  STALE: 1,
  ACTIVE: 2,
  FLAT: 3,
};

export function currentPositions(
  positions: PositionSnapshot[],
): PositionSnapshot[] {
  return positions
    .filter((position) => position.status !== "FLAT")
    .sort(
      (left, right) =>
        statusPriority[left.status] - statusPriority[right.status] ||
        left.symbol.localeCompare(right.symbol),
    );
}

export function summarizePositions(positions: PositionSnapshot[]) {
  const current = positions.filter((position) => position.status !== "FLAT");
  return {
    current: current.length,
    active: current.filter((position) => position.status === "ACTIVE").length,
    uncertain: current.filter((position) =>
      ["STALE", "UNKNOWN"].includes(position.status),
    ).length,
  };
}

function decimalNumber(value?: string): number | null {
  if (!value) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function moneyText(value?: string): string {
  const parsed = decimalNumber(value);
  if (parsed === null) return "数据源未提供";
  return `${new Intl.NumberFormat("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(parsed)} USDT`;
}

export function pnlText(value?: string): string {
  const parsed = decimalNumber(value);
  if (parsed === null) return "数据源未提供";
  const prefix = parsed > 0 ? "+" : "";
  return `${prefix}${new Intl.NumberFormat("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(parsed)} USDT`;
}

export function priceText(value?: string): string {
  const parsed = decimalNumber(value);
  if (parsed === null) return "数据源未提供";
  return new Intl.NumberFormat("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 8,
  }).format(parsed);
}

export function quantityText(value?: string): string {
  const parsed = decimalNumber(value);
  if (parsed === null) return "数据源未提供";
  return new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 8,
  }).format(parsed);
}

export function leverageText(value?: string): string {
  const parsed = decimalNumber(value);
  if (parsed === null) return "数据源未提供";
  return `${new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 2,
  }).format(parsed)}x`;
}
