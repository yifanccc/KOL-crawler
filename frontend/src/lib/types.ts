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
