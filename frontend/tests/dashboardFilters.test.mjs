import assert from "node:assert/strict";
import test from "node:test";

const filters = await import("../src/lib/dashboardFilters.ts");

test("actionable filter toggles and resets", () => {
  assert.equal(filters.defaultDashboardFilters.actionableOnly, false);

  const enabled = filters.toggleActionableOnly(filters.defaultDashboardFilters);
  assert.equal(enabled.actionableOnly, true);

  assert.equal(filters.toggleActionableOnly(enabled).actionableOnly, false);
});
