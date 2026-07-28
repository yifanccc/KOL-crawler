import assert from "node:assert/strict";
import test from "node:test";

const policy = await import("../src/lib/refreshPolicy.ts").catch(() => ({
  isBlockingRefresh: () => true,
}));

test("initial load is blocking", () => {
  assert.equal(policy.isBlockingRefresh(false), true);
});

test("refresh after successful data load is non-blocking", () => {
  assert.equal(policy.isBlockingRefresh(true), false);
});

test("background refresh failure preserves existing content", () => {
  const error = policy.refreshErrorMessage?.(true, "request failed") ?? "request failed";
  assert.equal(error, "");
});
