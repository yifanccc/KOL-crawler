import assert from "node:assert/strict";
import test from "node:test";

const api = await import("../src/lib/api.ts");
const platforms = await import("../src/lib/platforms.ts");


test("settings exposes every subscription platform through one entry", () => {
  assert.deepEqual(
    platforms.configurablePlatforms(["x", "binance_copy", "binance_square"]),
    ["x", "binance_copy", "binance_square"],
  );
  assert.equal(platforms.requiresPromptConfiguration("binance_copy"), false);
  assert.equal(platforms.requiresPromptConfiguration("x"), true);
});

test("Binance Copy create payload has no model or prompt fields", () => {
  const payload = api.buildBinanceCopyCreatePayload({
    handle: "熬鹰资本",
    accountId: "5075281354358777856",
    positionStartAt: "2026-08-19T00:00",
    enabled: true,
    ntfyServer: "https://ntfy.sh",
    ntfyTopic: "kol-copy",
  });

  assert.deepEqual(payload, {
    platform: "binance_copy",
    handle: "熬鹰资本",
    accountId: "5075281354358777856",
    positionStartAt: "2026-08-18T16:00:00.000Z",
    intervalMinutes: 1,
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
      positionStartAt: "2026-08-19T00:00",
      enabled: false,
      ntfyServer: "",
      ntfyTopic: "",
    }),
    {
      enabled: false,
      positionStartAt: "2026-08-18T16:00:00.000Z",
      ntfyServer: "",
      ntfyTopic: "",
    },
  );
});

test("Binance Copy start time is interpreted as Beijing time", () => {
  assert.equal(
    api.beijingDateTimeToIso("2026-08-19T00:00"),
    "2026-08-18T16:00:00.000Z",
  );
  assert.equal(
    api.isoToBeijingDateTimeLocal("2026-08-18T16:00:00Z"),
    "2026-08-19T00:00",
  );
});
