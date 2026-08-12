import assert from "node:assert/strict";
import test from "node:test";

const positions = await import("../src/lib/positions.ts");


const base = {
  subscriptionId: 5,
  kolId: "8",
  kolName: "熬鹰资本",
  platform: "binance_copy",
  accountId: "5075281354358777856",
  symbol: "BTCUSDT",
  positionSide: "SHORT",
  side: "SHORT",
  quantity: "10.43100000",
  confidence: "LOW",
  status: "ACTIVE",
  asOfEventTime: "2026-08-12T15:07:01Z",
  updatedAt: "2026-08-12T15:07:01Z",
};

test("current holdings exclude flat rows and put uncertain states first", () => {
  const rows = positions.currentPositions([
    { ...base, symbol: "SOLUSDT", status: "FLAT", side: "FLAT", quantity: "0" },
    { ...base, symbol: "BTCUSDT", status: "ACTIVE" },
    { ...base, symbol: "ETHUSDT", status: "STALE" },
    { ...base, symbol: "BNBUSDT", status: "UNKNOWN", side: "UNKNOWN" },
  ]);

  assert.deepEqual(rows.map((row) => row.symbol), ["BNBUSDT", "ETHUSDT", "BTCUSDT"]);
});

test("position summary distinguishes live and uncertain rows", () => {
  assert.deepEqual(
    positions.summarizePositions([
      { ...base, status: "ACTIVE" },
      { ...base, symbol: "ETHUSDT", status: "STALE" },
      { ...base, symbol: "SOLUSDT", status: "FLAT", side: "FLAT", quantity: "0" },
    ]),
    { current: 2, active: 1, uncertain: 1 },
  );
});
