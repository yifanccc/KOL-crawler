export type Stance = "long" | "short" | "neutral" | "unknown";

export interface Asset {
  id: string;
  symbol: string;
  name: string;
  market?: string;
  assetType?: string;
  signalCount?: number;
}

export interface Kol {
  id: string;
  name: string;
  handle?: string;
  platform?: string;
  avatarUrl?: string;
  description?: string;
  primaryMarket?: string;
  credibility?: number;
  signalCount?: number;
}

export interface SignalAsset {
  symbol: string;
  name?: string;
}

export interface Signal {
  id: string;
  kol: Kol;
  platform: string;
  url?: string;
  stance: Stance;
  actionable: boolean;
  summary: string;
  confidence?: number;
  publishedAt?: string;
  assets: SignalAsset[];
  tags: string[];
  evidence: string[];
  rawText?: string;
  translation?: string;
  importance: number;
  modelConfidence?: string;
  promptVersion?: string;
  market?: string;
  actionHint?: string;
  sourceLanguage?: string;
  riskWarning?: string;
  structuredStatus?: string;
}

export interface SignalQuery {
  kolId?: string;
  platform?: string;
  symbol?: string;
  tag?: string;
  stance?: string;
  actionable?: boolean;
  timeRange?: string;
  minImportance?: number;
  limit?: number;
  offset?: number;
}

export interface SignalPage {
  items: Signal[];
  total: number;
  overallTotal: number;
  actionableTotal: number;
  limit: number;
  offset: number;
}

export interface AdminSubscription {
  id: number;
  platform: string;
  handle: string;
  accountId?: string | null;
  positionStartAt?: string | null;
  visibility: "public" | "private";
  intervalMinutes: number;
  enabled: boolean;
  checkpoint?: string | null;
  prompt?: string | null;
  systemPrompt?: string | null;
  userPrompt?: string | null;
  outputSchema?: Record<string, unknown> | null;
  markets: string[];
  promptVersion?: string;
  effectiveSystemPrompt: string;
  effectiveUserPrompt: string;
  effectiveOutputSchema: Record<string, unknown>;
  ntfyServer?: string | null;
  ntfyTopic?: string | null;
  lastSuccessAt?: string | null;
}

export interface AdminConfigOptions {
  platforms: string[];
  markets: string[];
  defaultIntervalMinutes: number;
  defaultSystemPrompt: string;
  defaultUserPrompt: string;
  defaultOutputSchema: Record<string, unknown>;
  defaultNtfyServer: string;
  defaultNtfyTopic: string;
  collectorHealth?: CollectorHealth | null;
}

export interface CollectorProviderHealth {
  platform: string;
  status: string;
  message?: string;
}

export interface CollectorHealth {
  agentId: string;
  status: string;
  providers: CollectorProviderHealth[];
  outboxPending: number;
  lastSeenAt: string;
}

export interface PositionSnapshot {
  subscriptionId: number;
  kolId: string;
  kolName: string;
  platform: string;
  accountId: string;
  symbol: string;
  positionSide: "LONG" | "SHORT" | "UNKNOWN";
  side: "LONG" | "SHORT" | "FLAT" | "UNKNOWN";
  quantity?: string;
  entryPrice?: string;
  currentPrice?: string;
  notional?: string;
  estimatedPnl?: string;
  priceUpdatedAt?: string;
  confidence: "HIGH" | "MEDIUM" | "LOW" | "UNKNOWN";
  status: "ACTIVE" | "FLAT" | "UNKNOWN" | "STALE";
  asOfEventTime?: string;
  staleSince?: string;
  updatedAt: string;
}

export interface PositionKolSummary {
  subscriptionId: number;
  kolId: string;
  kolName: string;
  platform: string;
  accountId: string;
  marginBalance?: string;
  totalPositionNotional?: string;
  estimatedPnl?: string;
  uncertainPositionCount: number;
  metricsStatus: "COMPLETE" | "PARTIAL" | "UNKNOWN";
  updatedAt?: string;
}

export interface PositionKolDetail {
  summary: PositionKolSummary;
  positions: PositionSnapshot[];
}

export interface PositionOperation {
  sourceRecordId: string;
  revision: string;
  action: "OPEN" | "ADD" | "REDUCE" | "CLOSE" | "REVERSE" | "CORRECTION";
  effectiveAction: string;
  symbol: string;
  positionSide: "LONG" | "SHORT" | "UNKNOWN";
  quantity?: string;
  price?: string;
  amount?: string;
  realizedPnl?: string;
  eventTime: string;
}

export interface PositionOperationPage {
  items: PositionOperation[];
  total: number;
  limit: number;
  offset: number;
}
