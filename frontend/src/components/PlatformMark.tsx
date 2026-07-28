"use client";

export function PlatformMark({ platform, withLabel = false }: { platform: string; withLabel?: boolean }) {
  const normalized = platform.toLowerCase();
  const isX = normalized === "x" || normalized === "twitter";
  const isBinance = normalized.includes("binance");
  const label = isX ? "X" : isBinance ? "Binance Square" : platform;
  const mark = isX ? "X" : isBinance ? "B" : platform.slice(0, 1).toUpperCase();

  return (
    <span className="platform-identity" aria-label={label} title={label}>
      <span className={`platform-mark ${isX ? "platform-mark-x" : isBinance ? "platform-mark-binance" : ""}`}>
        {mark}
      </span>
      {withLabel ? <span>{label}</span> : null}
    </span>
  );
}
