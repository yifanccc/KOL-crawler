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

export interface PositionExposureSide {
  count: number;
  notional: number | null;
  accountMultiple: number | null;
}

export interface PositionExposureSummary {
  long: PositionExposureSide;
  short: PositionExposureSide;
  longShare: number | null;
  shortShare: number | null;
  unresolvedCount: number;
  missingNotionalCount: number;
}

function decimalNumber(value?: string): number | null {
  if (!value) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function exposureSide(
  positions: PositionSnapshot[],
  side: "LONG" | "SHORT",
  marginBalance: number | null,
): PositionExposureSide {
  const rows = positions.filter(
    (position) =>
      position.side === side && ["ACTIVE", "STALE"].includes(position.status),
  );
  const values = rows.map((position) => decimalNumber(position.notional));
  const complete = values.every((value) => value !== null);
  const notional = complete
    ? values.reduce<number>((total, value) => total + (value ?? 0), 0)
    : null;
  return {
    count: rows.length,
    notional,
    accountMultiple:
      notional !== null && marginBalance !== null && marginBalance > 0
        ? notional / marginBalance
        : null,
  };
}

export function summarizePositionExposure(
  positions: PositionSnapshot[],
  marginBalance?: string,
): PositionExposureSummary {
  const current = currentPositions(positions);
  const balance = decimalNumber(marginBalance);
  const long = exposureSide(current, "LONG", balance);
  const short = exposureSide(current, "SHORT", balance);
  const gross =
    long.notional !== null && short.notional !== null
      ? long.notional + short.notional
      : null;
  return {
    long,
    short,
    longShare: gross !== null && gross > 0 ? long.notional! / gross : null,
    shortShare: gross !== null && gross > 0 ? short.notional! / gross : null,
    unresolvedCount: current.filter(
      (position) =>
        !["LONG", "SHORT"].includes(position.side) ||
        position.status === "UNKNOWN",
    ).length,
    missingNotionalCount: current.filter(
      (position) =>
        ["LONG", "SHORT"].includes(position.side) &&
        ["ACTIVE", "STALE"].includes(position.status) &&
        decimalNumber(position.notional) === null,
    ).length,
  };
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

export function accountMultipleText(
  notional?: string,
  marginBalance?: string,
): string {
  const notionalValue = decimalNumber(notional);
  const marginValue = decimalNumber(marginBalance);
  if (notionalValue === null || marginValue === null || marginValue <= 0) {
    return "暂不可估算";
  }
  return multipleText(notionalValue / marginValue);
}

export function multipleText(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "暂不可估算";
  return `${new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 2,
  }).format(value)}x`;
}
