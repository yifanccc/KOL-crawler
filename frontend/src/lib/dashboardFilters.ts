import type { Stance } from "./types";

export interface DashboardFilters {
  kolId: string;
  platform: string;
  stance: "" | Stance;
  symbol: string;
  tag: string;
  timeRange: string;
  minImportance: number;
  actionableOnly: boolean;
}

export const defaultDashboardFilters: DashboardFilters = {
  kolId: "",
  platform: "",
  stance: "",
  symbol: "",
  tag: "",
  timeRange: "all",
  minImportance: 1,
  actionableOnly: false,
};

export function toggleActionableOnly(filters: DashboardFilters): DashboardFilters {
  return { ...filters, actionableOnly: !filters.actionableOnly };
}
