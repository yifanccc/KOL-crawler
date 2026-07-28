"use client";

import { useEffect, useMemo, useState } from "react";
import type { Kol } from "@/lib/types";

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "K";
  return parts.slice(0, 2).map((part) => part[0]?.toUpperCase()).join("");
}

export function KolAvatar({
  kol,
  platform = "x",
  size = 36,
}: {
  kol: Kol;
  platform?: string;
  size?: number;
}) {
  const fallbackUrl = useMemo(() => {
    const normalizedPlatform = platform.toLowerCase();
    if (!kol.handle || !["x", "twitter"].includes(normalizedPlatform)) return "";
    return `https://unavatar.io/x/${encodeURIComponent(kol.handle.replace(/^@/, ""))}`;
  }, [kol.handle, platform]);
  const source = kol.avatarUrl || fallbackUrl;
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
  }, [source]);

  if (source && !failed) {
    return (
      <img
        className="kol-avatar"
        src={source}
        alt={`${kol.name} 头像`}
        width={size}
        height={size}
        loading="lazy"
        onError={() => setFailed(true)}
      />
    );
  }

  return (
    <span className="kol-avatar kol-avatar-fallback" style={{ width: size, height: size }} aria-label={`${kol.name} 头像`}>
      {initials(kol.name)}
    </span>
  );
}
