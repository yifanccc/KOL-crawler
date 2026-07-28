import assert from "node:assert/strict";
import test from "node:test";

const api = await import("../src/lib/api.ts");

test("signal query serializes filters and pagination", () => {
  const query = api.buildSignalQuery({
    kolId: "7",
    platform: "X",
    symbol: "NVDA",
    tag: "AI",
    stance: "long",
    actionable: true,
    timeRange: "24h",
    minImportance: 3,
    limit: 25,
    offset: 50,
  });

  assert.equal(
    query,
    "kol_id=7&platform=X&symbol=NVDA&tag=AI&stance=long&actionable=true&time_range=24h&min_importance=3&limit=25&offset=50",
  );
});
