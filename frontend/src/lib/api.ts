import type {
  AdminConfigOptions,
  AdminSubscription,
  Asset,
  CollectorHealth,
  Kol,
  PositionSnapshot,
  Signal,
  SignalAsset,
  SignalPage,
  SignalQuery,
  Stance,
} from "./types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ||
  "http://localhost:8000";
const APP_BASE_PATH = (process.env.NEXT_PUBLIC_BASE_PATH || "").replace(/\/$/, "");

function appPath(path: string): string {
  return `${APP_BASE_PATH}${path}` || "/";
}

function currentAppLocation(): string {
  const pathname = APP_BASE_PATH && window.location.pathname.startsWith(APP_BASE_PATH)
    ? window.location.pathname.slice(APP_BASE_PATH.length) || "/"
    : window.location.pathname;
  return `${pathname}${window.location.search}`;
}

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function text(value: unknown, fallback = ""): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function idText(value: unknown, fallback = ""): string {
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return text(value, fallback);
}

function numberValue(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function normalizeItems(value: unknown): unknown[] {
  if (isRecord(value) && Array.isArray(value.items)) return value.items;
  if (Array.isArray(value)) return value;
  return [];
}

function normalizeStance(value: unknown): Stance {
  const stance = text(value).toLowerCase();
  if (["long", "bullish", "多"].includes(stance)) return "long";
  if (["short", "bearish", "空"].includes(stance)) return "short";
  if (["neutral", "watch", "中性", "无明确观点"].includes(stance)) return "neutral";
  return "unknown";
}

function normalizeKol(value: unknown): Kol {
  const source = isRecord(value) ? value : {};
  const name = text(source.name, text(source.displayName, text(source.handle, "未知 KOL")));
  return {
    id: idText(source.id, text(source.handle, name)),
    name,
    handle: text(source.handle, text(source.displayName)),
    platform: text(source.platform),
    avatarUrl: text(source.avatar_url, text(source.avatarUrl)),
    description: text(source.description),
    primaryMarket: text(source.primaryMarket, text(source.primary_market)),
    credibility: numberValue(source.credibility),
    signalCount: numberValue(source.signal_count) ?? numberValue(source.signalCount),
  };
}

function normalizeAssets(value: unknown): SignalAsset[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (typeof item === "string") return { symbol: item };
      if (!isRecord(item)) return null;
      const symbol = text(item.symbol, text(item.ticker));
      if (!symbol) return null;
      return {
        symbol,
        name: text(item.name),
      };
    })
    .filter((item): item is SignalAsset => Boolean(item));
}

function normalizeTags(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const tags = value.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
  return Array.from(new Set(tags.map((item) => item.trim())));
}

function normalizeCollectorHealth(value: unknown): CollectorHealth | null {
  if (!isRecord(value)) return null;
  const providers = Array.isArray(value.providers)
    ? value.providers.flatMap((provider) => {
        if (!isRecord(provider)) return [];
        const platform = text(provider.platform);
        const status = text(provider.status);
        return platform && status
          ? [{ platform, status, message: text(provider.message) || undefined }]
          : [];
      })
    : [];
  const agentId = text(value.agentId);
  const status = text(value.status);
  const lastSeenAt = text(value.lastSeenAt);
  if (!agentId || !status || !lastSeenAt) return null;
  return {
    agentId,
    status,
    providers,
    outboxPending: numberValue(value.outboxPending) ?? 0,
    lastSeenAt,
  };
}

function normalizeSignal(value: unknown, index: number): Signal {
  const source = isRecord(value) ? value : {};
  const confidenceText = text(source.confidence);
  const confidenceMap: Record<string, number> = { 高: 0.9, 中: 0.62, 低: 0.35 };
  const evidence = normalizeTags(source.evidence);
  const tags = normalizeTags(source.tags);
  const importance = numberValue(source.importance);
  const normalizedKol = normalizeKol(source.kol);
  const kol = {
    ...normalizedKol,
    handle: normalizedKol.handle || text(source.sourceName),
  };
  return {
    id: idText(source.id, `signal-${index}`),
    kol,
    platform: text(source.platform, "unknown"),
    url: text(source.url),
    stance: normalizeStance(source.stance),
    actionable: Boolean(source.actionable),
    summary: text(source.summary, "暂无摘要"),
    confidence: numberValue(source.confidence) ?? confidenceMap[confidenceText],
    publishedAt: text(source.published_at, text(source.publishedAt)),
    assets: normalizeAssets(source.assets),
    tags,
    evidence: evidence.length ? evidence : tags.slice(0, 3),
    rawText: text(source.rawText, text(source.raw_text)),
    translation: text(source.translation, text(source.summary)),
    importance: Math.max(1, Math.min(5, Math.round(importance ?? (source.actionable ? 4 : 2)))),
    modelConfidence: text(source.modelConfidence, confidenceText),
    promptVersion: text(source.promptVersion, "default-v1"),
    market: text(source.market, "unknown"),
    actionHint: text(source.actionHint),
    sourceLanguage: text(source.sourceLanguage),
    riskWarning: text(source.riskWarning),
    structuredStatus: text(source.structuredStatus),
  };
}

function normalizeAsset(value: unknown, index: number): Asset {
  const source = isRecord(value) ? value : {};
  const symbol = text(source.symbol, text(source.ticker, `ASSET-${index + 1}`));
  return {
    id: idText(source.id, symbol),
    symbol,
    name: text(source.name, symbol),
    market: text(source.market),
    assetType: text(source.assetType, text(source.asset_type)),
    signalCount: numberValue(source.signal_count) ?? numberValue(source.signalCount),
  };
}

async function getJson(path: string): Promise<unknown> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
    credentials: "include",
  });

  if (!response.ok) {
    if (response.status === 401 && typeof window !== "undefined") {
      const next = currentAppLocation();
      window.location.assign(`${appPath("/login")}?next=${encodeURIComponent(next)}`);
    }
    throw new Error(`请求失败：${response.status}`);
  }

  if (response.status === 204) return null;
  return response.json();
}

async function sendJson(path: string, options: RequestInit): Promise<unknown> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    credentials: "include",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });

  if (!response.ok) {
    if (response.status === 401 && typeof window !== "undefined") {
      const next = currentAppLocation();
      window.location.assign(`${appPath("/login")}?next=${encodeURIComponent(next)}`);
    }
    throw new Error(`请求失败：${response.status}`);
  }

  return response.json();
}

export function buildSignalQuery(params: SignalQuery = {}): string {
  const search = new URLSearchParams();
  if (params.kolId) search.set("kol_id", params.kolId);
  if (params.platform) search.set("platform", params.platform);
  if (params.symbol) search.set("symbol", params.symbol);
  if (params.tag) search.set("tag", params.tag);
  if (params.stance) search.set("stance", params.stance);
  if (typeof params.actionable === "boolean") {
    search.set("actionable", String(params.actionable));
  }
  if (params.timeRange) search.set("time_range", params.timeRange);
  if (typeof params.minImportance === "number") {
    search.set("min_importance", String(params.minImportance));
  }
  if (typeof params.limit === "number") search.set("limit", String(params.limit));
  if (typeof params.offset === "number") search.set("offset", String(params.offset));
  return search.toString();
}

export function signalEndpoint(scope: "regular" | "private"): string {
  return scope === "private" ? "/api/admin/signals" : "/api/signals";
}

export function normalizeSignalPage(
  json: unknown,
  params: SignalQuery = {},
): SignalPage {
  const items = normalizeItems(json).map(normalizeSignal);
  const source = isRecord(json) ? json : {};
  const total = numberValue(source.total) ?? items.length;
  return {
    items,
    total,
    overallTotal: numberValue(source.overallTotal) ?? total,
    actionableTotal:
      numberValue(source.actionableTotal) ??
      items.filter((signal) => signal.actionable).length,
    limit: numberValue(source.limit) ?? params.limit ?? 100,
    offset: numberValue(source.offset) ?? params.offset ?? 0,
  };
}

export async function fetchSignalPage(params: SignalQuery = {}): Promise<SignalPage> {
  const query = buildSignalQuery(params);
  const endpoint = signalEndpoint("regular");
  const json = await getJson(`${endpoint}${query ? `?${query}` : ""}`);
  return normalizeSignalPage(json, params);
}

export async function fetchPrivateSignalPage(
  params: SignalQuery = {},
): Promise<SignalPage> {
  const query = buildSignalQuery(params);
  const endpoint = signalEndpoint("private");
  const json = await getJson(`${endpoint}${query ? `?${query}` : ""}`);
  return normalizeSignalPage(json, params);
}

export async function fetchSignals(params: SignalQuery = {}): Promise<Signal[]> {
  return (await fetchSignalPage(params)).items;
}

export async function fetchKols(): Promise<Kol[]> {
  const json = await getJson("/api/kols");
  return normalizeItems(json).map(normalizeKol);
}

export async function fetchAssets(): Promise<Asset[]> {
  const json = await getJson("/api/assets");
  return normalizeItems(json).map(normalizeAsset);
}

export async function fetchCollectorHealth(): Promise<CollectorHealth | null> {
  const json = await getJson("/api/collector-health");
  return isRecord(json) ? normalizeCollectorHealth(json.item) : null;
}

export function normalizePositions(value: unknown): PositionSnapshot[] {
  return normalizeItems(value).flatMap((item) => {
    if (!isRecord(item)) return [];
    const kol = isRecord(item.kol) ? item.kol : {};
    const symbol = text(item.symbol);
    const updatedAt = text(item.updatedAt);
    if (!symbol || !updatedAt) return [];
    return [
      {
        subscriptionId: numberValue(item.subscriptionId) ?? 0,
        kolId: idText(kol.id),
        kolName: text(kol.displayName, "未知 KOL"),
        platform: text(item.platform),
        accountId: text(item.accountId),
        symbol,
        positionSide: ["LONG", "SHORT", "UNKNOWN"].includes(
          text(item.positionSide),
        )
          ? (text(item.positionSide) as PositionSnapshot["positionSide"])
          : "UNKNOWN",
        side: ["LONG", "SHORT", "FLAT", "UNKNOWN"].includes(text(item.side))
          ? (text(item.side) as PositionSnapshot["side"])
          : "UNKNOWN",
        quantity: text(item.quantity) || undefined,
        confidence: ["HIGH", "MEDIUM", "LOW", "UNKNOWN"].includes(
          text(item.confidence),
        )
          ? (text(item.confidence) as PositionSnapshot["confidence"])
          : "UNKNOWN",
        status: ["ACTIVE", "FLAT", "UNKNOWN", "STALE"].includes(
          text(item.status),
        )
          ? (text(item.status) as PositionSnapshot["status"])
          : "UNKNOWN",
        asOfEventTime: text(item.asOfEventTime) || undefined,
        staleSince: text(item.staleSince) || undefined,
        updatedAt,
      },
    ];
  });
}

export async function fetchPositions(): Promise<PositionSnapshot[]> {
  return normalizePositions(await getJson("/api/positions"));
}

export async function login(username: string, password: string): Promise<void> {
  const json = await sendJson("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  if (!isRecord(json)) throw new Error("登录响应无效");
}

export async function logout(): Promise<void> {
  await sendJson("/api/auth/logout", { method: "POST" });
}

function normalizeAdminSubscription(value: unknown): AdminSubscription {
  const source = isRecord(value) ? value : {};
  return {
    id: numberValue(source.id) ?? 0,
    platform: text(source.platform, "x"),
    handle: text(source.handle, "unknown"),
    accountId: text(source.accountId) || null,
    visibility: source.visibility === "private" ? "private" : "public",
    intervalMinutes: numberValue(source.intervalMinutes) ?? 10,
    enabled: source.enabled !== false,
    checkpoint: text(source.checkpoint) || null,
    prompt: text(source.prompt) || null,
    systemPrompt: text(source.systemPrompt) || null,
    userPrompt: text(source.userPrompt) || null,
    outputSchema: isRecord(source.outputSchema) ? source.outputSchema : null,
    markets: normalizeTags(source.markets),
    promptVersion: text(source.promptVersion, "default-v2"),
    effectiveSystemPrompt: text(source.effectiveSystemPrompt),
    effectiveUserPrompt: text(source.effectiveUserPrompt),
    effectiveOutputSchema: isRecord(source.effectiveOutputSchema) ? source.effectiveOutputSchema : {},
    ntfyServer: text(source.ntfyServer) || null,
    ntfyTopic: text(source.ntfyTopic) || null,
    lastSuccessAt: text(source.lastSuccessAt) || null,
  };
}

export async function fetchAdminSubscriptions(): Promise<AdminSubscription[]> {
  const json = await getJson("/api/admin/subscriptions");
  return normalizeItems(json).map(normalizeAdminSubscription);
}

export async function fetchAdminConfigOptions(): Promise<AdminConfigOptions> {
  const json = await getJson("/api/admin/config-options");
  if (!isRecord(json)) throw new Error("配置响应无效");
  return {
    platforms: normalizeTags(json.platforms),
    markets: normalizeTags(json.markets),
    defaultIntervalMinutes: numberValue(json.defaultIntervalMinutes) ?? 10,
    defaultSystemPrompt: text(json.defaultSystemPrompt),
    defaultUserPrompt: text(json.defaultUserPrompt),
    defaultOutputSchema: isRecord(json.defaultOutputSchema) ? json.defaultOutputSchema : {},
    defaultNtfyServer: text(json.defaultNtfyServer),
    defaultNtfyTopic: text(json.defaultNtfyTopic),
    collectorHealth: normalizeCollectorHealth(json.collectorHealth),
  };
}

export interface AdminSubscriptionInput {
  platform: string;
  handle: string;
  accountId?: string;
  intervalMinutes: number;
  systemPrompt: string;
  userPrompt: string;
  outputSchema: Record<string, unknown>;
  markets: string[];
  ntfyServer: string;
  ntfyTopic: string;
  enabled?: boolean;
}

export async function createAdminSubscription(
  payload: AdminSubscriptionInput,
): Promise<AdminSubscription> {
  const json = await sendJson("/api/admin/subscriptions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!isRecord(json)) throw new Error("创建响应无效");
  return normalizeAdminSubscription(json.item);
}

export async function updateAdminSubscription(
  id: number,
  payload: Omit<AdminSubscriptionInput, "platform" | "handle" | "accountId">,
): Promise<AdminSubscription> {
  const json = await sendJson(`/api/admin/subscriptions/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  if (!isRecord(json)) throw new Error("更新响应无效");
  return normalizeAdminSubscription(json.item);
}

export async function deleteAdminSubscription(id: number): Promise<void> {
  await sendJson(`/api/admin/subscriptions/${id}`, { method: "DELETE" });
}
