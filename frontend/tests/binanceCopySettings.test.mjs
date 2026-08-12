import assert from "node:assert/strict";
import test from "node:test";

const api = await import("../src/lib/api.ts");
const platforms = await import("../src/lib/platforms.ts");


test("generic settings exclude private trade platforms", () => {
  assert.deepEqual(
    platforms.contentPlatforms(["x", "binance_copy", "binance_square"]),
    ["x", "binance_square"],
  );
});

test("Binance Copy create payload has no model or prompt fields", () => {
  const payload = api.buildBinanceCopyCreatePayload({
    handle: "熬鹰资本",
    accountId: "5075281354358777856",
    enabled: true,
    ntfyServer: "https://ntfy.sh",
    ntfyTopic: "kol-copy",
  });

  assert.deepEqual(payload, {
    platform: "binance_copy",
    handle: "熬鹰资本",
    accountId: "5075281354358777856",
    intervalMinutes: 10,
    markets: ["crypto"],
    ntfyServer: "https://ntfy.sh",
    ntfyTopic: "kol-copy",
  });
  assert.equal("systemPrompt" in payload, false);
  assert.equal("userPrompt" in payload, false);
  assert.equal("outputSchema" in payload, false);
});

test("Binance Copy update payload only contains mutable controls", () => {
  assert.deepEqual(
    api.buildBinanceCopyUpdatePayload({
      handle: "ignored identity",
      accountId: "5075281354358777856",
      enabled: false,
      ntfyServer: "",
      ntfyTopic: "",
    }),
    { enabled: false, ntfyServer: "", ntfyTopic: "" },
  );
});
