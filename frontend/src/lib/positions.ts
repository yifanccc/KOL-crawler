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
