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

test("exposure summary separates priced long and short notionals", () => {
  const summary = positions.summarizePositionExposure(
    [
      { ...base, symbol: "BTCUSDT", side: "LONG", positionSide: "LONG", notional: "5000" },
      { ...base, symbol: "ETHUSDT", side: "SHORT", positionSide: "SHORT", notional: "2000" },
    ],
    "10000",
  );

  assert.deepEqual(summary, {
    long: { count: 1, notional: 5000, accountMultiple: 0.5 },
    short: { count: 1, notional: 2000, accountMultiple: 0.2 },
    longShare: 5 / 7,
    shortShare: 2 / 7,
    unresolvedCount: 0,
    missingNotionalCount: 0,
  });
  assert.equal(positions.accountMultipleText("7000", "10000"), "0.7x");
});

test("exposure summary does not turn missing notional into zero", () => {
  const summary = positions.summarizePositionExposure([
    { ...base, symbol: "BTCUSDT", side: "LONG", positionSide: "LONG" },
  ]);

  assert.equal(summary.long.notional, null);
  assert.equal(summary.longShare, null);
  assert.equal(summary.unresolvedCount, 0);
  assert.equal(summary.missingNotionalCount, 1);
});

test("exposure summary reports unresolved rows excluded from the split", () => {
  const summary = positions.summarizePositionExposure([
    { ...base, symbol: "BTCUSDT", side: "SHORT", positionSide: "SHORT", notional: "2000" },
    {
      ...base,
      symbol: "SNDKUSDT",
      side: "UNKNOWN",
      positionSide: "LONG",
      status: "UNKNOWN",
    },
  ]);

  assert.equal(summary.short.notional, 2000);
  assert.equal(summary.shortShare, 1);
  assert.equal(summary.unresolvedCount, 1);
  assert.equal(summary.missingNotionalCount, 0);
});
