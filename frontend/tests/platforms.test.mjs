import assert from "node:assert/strict";
import test from "node:test";

const platforms = await import("../src/lib/platforms.ts");

test("Binance Copy requires an immutable account id", () => {
  assert.equal(platforms.requiresAccountId("binance_copy"), true);
  assert.equal(platforms.requiresAccountId("binance_square"), false);
  assert.equal(platforms.requiresAccountId("x"), false);
  assert.equal(platforms.requiresAccountId("okx_orbit"), false);
});

test("supported platform labels are explicit", () => {
  assert.equal(platforms.platformLabel("x"), "X");
  assert.equal(platforms.platformLabel("binance_copy"), "Binance Copy");
  assert.equal(platforms.platformLabel("binance_square"), "Binance 广场");
  assert.equal(platforms.platformLabel("future_source"), "future_source");
});
