import assert from "node:assert/strict";
import test from "node:test";

const api = await import("../src/lib/api.ts");


test("position snapshots normalize the private holdings contract", () => {
  const positions = api.normalizePositions({
    items: [
      {
        subscriptionId: 5,
        kol: { id: 8, displayName: "熬鹰资本" },
        platform: "binance_copy",
        accountId: "5075281354358777856",
        symbol: "BTCUSDT",
        positionSide: "SHORT",
        side: "SHORT",
        quantity: "10.43100000",
        confidence: "LOW",
        status: "ACTIVE",
        asOfEventTime: "2026-08-12T15:07:01Z",
        staleSince: null,
        updatedAt: "2026-08-12T15:07:01Z",
      },
    ],
  });

  assert.deepEqual(positions, [
    {
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
      staleSince: undefined,
      updatedAt: "2026-08-12T15:07:01Z",
    },
  ]);
});
