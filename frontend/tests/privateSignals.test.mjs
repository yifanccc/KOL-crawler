import assert from "node:assert/strict";
import test from "node:test";

const api = await import("../src/lib/api.ts");

test("private signal requests use the admin endpoint", () => {
  assert.equal(api.signalEndpoint("private"), "/api/admin/signals");
  assert.equal(api.signalEndpoint("regular"), "/api/signals");
});

test("private signal pages share the regular response normalizer", () => {
  const page = api.normalizeSignalPage(
    {
      items: [
        {
          id: 9,
          kol: { id: 3, displayName: "熬鹰资本" },
          platform: "BINANCE_COPY",
          stance: "中性",
          actionable: true,
          summary: "BTCUSDT 减仓",
          assets: ["BTCUSDT"],
          tags: ["交易记录"],
          evidence: ["推测持仓 LONG 0.11"],
          importance: 3,
          structuredStatus: "deterministic",
        },
      ],
      total: 21,
      overallTotal: 25,
      actionableTotal: 25,
      limit: 20,
      offset: 0,
    },
    { limit: 10, offset: 10 },
  );

  assert.equal(page.items[0].kol.name, "熬鹰资本");
  assert.equal(page.items[0].structuredStatus, "deterministic");
  assert.deepEqual(page.items[0].assets, [{ symbol: "BTCUSDT" }]);
  assert.equal(page.total, 21);
  assert.equal(page.limit, 20);
  assert.equal(page.offset, 0);
});
