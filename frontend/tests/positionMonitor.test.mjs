import assert from "node:assert/strict";
import test from "node:test";

const api = await import("../src/lib/api.ts");
const positions = await import("../src/lib/positions.ts");


const summary = {
  subscriptionId: 5,
  kol: { id: 8, displayName: "熬鹰资本" },
  platform: "binance_copy",
  accountId: "5075281354358777856",
  marginBalance: "137889.65",
  totalPositionNotional: "5720.00",
  estimatedPnl: "110.00",
  uncertainPositionCount: 0,
  metricsStatus: "COMPLETE",
  updatedAt: "2026-08-12T15:08:00Z",
};

test("normalizes one KOL summary with only supported metrics", () => {
  assert.deepEqual(api.normalizePositionKols({ items: [summary] }), [
    {
      subscriptionId: 5,
      kolId: "8",
      kolName: "熬鹰资本",
      platform: "binance_copy",
      accountId: "5075281354358777856",
      marginBalance: "137889.65",
      totalPositionNotional: "5720.00",
      estimatedPnl: "110.00",
      uncertainPositionCount: 0,
      metricsStatus: "COMPLETE",
      updatedAt: "2026-08-12T15:08:00Z",
    },
  ]);
});

test("normalizes KOL detail positions and operation pagination", () => {
  const detail = api.normalizePositionKolDetail({
    item: {
      summary,
      positions: [
        {
          symbol: "BTCUSDT",
          positionSide: "LONG",
          side: "LONG",
          quantity: "0.11",
          entryPrice: "51000",
          currentPrice: "52000",
          notional: "5720.00",
          estimatedPnl: "110.00",
          confidence: "LOW",
          status: "ACTIVE",
          asOfEventTime: "2026-08-12T15:07:01Z",
          priceUpdatedAt: "2026-08-12T15:08:00Z",
          staleSince: null,
          updatedAt: "2026-08-12T15:08:00Z",
        },
      ],
    },
  });
  assert.equal(detail?.summary.kolName, "熬鹰资本");
  assert.equal(detail?.positions[0].entryPrice, "51000");

  assert.deepEqual(
    api.normalizePositionOperations(
      {
        items: [
          {
            sourceRecordId: "2",
            revision: "r1",
            action: "ADD",
            effectiveAction: "INCREASE",
            symbol: "BTCUSDT",
            positionSide: "LONG",
            quantity: "0.05",
            price: "53000",
            amount: "2650.00",
            realizedPnl: "0",
            eventTime: "2026-08-12T15:02:00Z",
          },
        ],
        total: 2,
        limit: 1,
        offset: 0,
      },
      { limit: 1, offset: 0 },
    ),
    {
      items: [
        {
          sourceRecordId: "2",
          revision: "r1",
          action: "ADD",
          effectiveAction: "INCREASE",
          symbol: "BTCUSDT",
          positionSide: "LONG",
          quantity: "0.05",
          price: "53000",
          amount: "2650.00",
          realizedPnl: "0",
          eventTime: "2026-08-12T15:02:00Z",
        },
      ],
      total: 2,
      limit: 1,
      offset: 0,
    },
  );
});

test("financial formatting distinguishes missing values and estimated pnl", () => {
  assert.equal(positions.moneyText(undefined), "数据源未提供");
  assert.equal(positions.moneyText("5720"), "5,720.00 USDT");
  assert.equal(positions.pnlText("110"), "+110.00 USDT");
  assert.equal(positions.pnlText("-9.5"), "-9.50 USDT");
});
