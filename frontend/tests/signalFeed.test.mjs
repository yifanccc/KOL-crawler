import assert from "node:assert/strict";
import test from "node:test";

const feed = await import("../src/lib/signalFeed.ts");

function signal(id) {
  return { id: String(id) };
}

test("homepage loads signals in small batches", () => {
  assert.equal(feed.SIGNAL_BATCH_SIZE, 20);
});

test("next signal page appends unique items and advances the consumed offset", () => {
  const current = {
    items: [signal(1), signal(2)],
    total: 5,
    overallTotal: 8,
    actionableTotal: 3,
    limit: 2,
    offset: 0,
  };
  const next = {
    items: [signal(2), signal(3)],
    total: 5,
    overallTotal: 8,
    actionableTotal: 3,
    limit: 2,
    offset: 2,
  };

  const result = feed.appendSignalPage(current, next);

  assert.deepEqual(result.page.items.map((item) => item.id), ["1", "2", "3"]);
  assert.equal(result.nextOffset, 4);
  assert.equal(feed.hasMoreSignals(result.nextOffset, result.page.total), true);
});

test("refreshed first page is prepended without discarding loaded signals", () => {
  const current = {
    items: [signal(2), signal(3)],
    total: 3,
    overallTotal: 3,
    actionableTotal: 1,
    limit: 2,
    offset: 0,
  };
  const refreshed = {
    items: [signal(1), signal(2)],
    total: 3,
    overallTotal: 3,
    actionableTotal: 1,
    limit: 2,
    offset: 0,
  };

  const result = feed.refreshSignalPage(current, refreshed);

  assert.deepEqual(result.items.map((item) => item.id), ["1", "2", "3"]);
  assert.equal(feed.loadedSignalsLabel(result.items.length, result.total), "已加载 3 / 3");
});
