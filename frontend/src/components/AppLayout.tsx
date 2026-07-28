"use client";

import { ReactNode } from "react";
import { HeaderSearch } from "./HeaderSearch";
import { Sidebar } from "./Sidebar";

interface AppLayoutProps {
  children: ReactNode;
  rightPanel: ReactNode;
  title?: string;
  eyebrow?: string;
  symbol: string;
  platform: string;
  platforms: string[];
  suggestions: string[];
  onSymbolChange: (symbol: string) => void;
  onPlatformChange: (platform: string) => void;
}

export function AppLayout({
  children,
  rightPanel,
  title,
  eyebrow,
  symbol,
  platform,
  platforms,
  suggestions,
  onSymbolChange,
  onPlatformChange,
}: AppLayoutProps) {
  return (
    <div className="dashboard-shell">
      <Sidebar />
      <div className="dashboard-stage">
        <HeaderSearch
          title={title}
          eyebrow={eyebrow}
          symbol={symbol}
          platform={platform}
          platforms={platforms}
          suggestions={suggestions}
          onSymbolChange={onSymbolChange}
          onPlatformChange={onPlatformChange}
        />
        <div className="dashboard-grid">
          <main className="dashboard-main">{children}</main>
          {rightPanel}
        </div>
      </div>
    </div>
  );
}
