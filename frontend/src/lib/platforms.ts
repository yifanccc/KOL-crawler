const PLATFORM_LABELS: Record<string, string> = {
  x: "X",
  binance_square: "Binance 广场",
  binance_copy: "Binance Copy",
};

const ACCOUNT_ID_PLATFORMS = new Set(["binance_copy"]);

export function platformLabel(platform: string): string {
  return PLATFORM_LABELS[platform.toLowerCase()] || platform;
}

export function requiresAccountId(platform: string): boolean {
  return ACCOUNT_ID_PLATFORMS.has(platform.toLowerCase());
}

export function contentPlatforms(platforms: string[]): string[] {
  return platforms.filter((platform) => !requiresAccountId(platform));
}
