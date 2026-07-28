"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { LogOut, Search, ShieldCheck, SlidersHorizontal } from "lucide-react";
import { logout } from "@/lib/api";

interface HeaderSearchProps {
  title?: string;
  eyebrow?: string;
  symbol: string;
  platform: string;
  platforms: string[];
  suggestions: string[];
  onSymbolChange: (symbol: string) => void;
  onPlatformChange: (platform: string) => void;
}

function normalizeSymbol(value: string) {
  return value.trim().replace(/^\$/, "").toUpperCase();
}

export function HeaderSearch({
  title = "金融 KOL 情报流 Dashboard",
  eyebrow = "Financial KOL Intelligence",
  symbol,
  platform,
  platforms,
  suggestions,
  onSymbolChange,
  onPlatformChange,
}: HeaderSearchProps) {
  const router = useRouter();
  const [draft, setDraft] = useState(symbol);

  useEffect(() => {
    setDraft(symbol);
  }, [symbol]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSymbolChange(normalizeSymbol(draft));
  }

  async function handleLogout() {
    await logout();
    router.replace("/login");
    router.refresh();
  }

  return (
    <header className="dashboard-header">
      <div>
        <p className="terminal-label">{eyebrow}</p>
        <h1>{title}</h1>
      </div>
      <form className="header-search" onSubmit={handleSubmit}>
        <button type="submit" aria-label="应用标的搜索" title="搜索">
          <Search size={17} aria-hidden="true" />
        </button>
        <input
          aria-label="搜索标的"
          list="global-symbol-options"
          placeholder="搜索 BTC / SPX / NVDA / AAPL"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        <datalist id="global-symbol-options">
          {suggestions.map((item) => (
            <option key={item} value={item} />
          ))}
        </datalist>
      </form>
      <label className="header-select">
        <SlidersHorizontal size={15} aria-hidden="true" />
        <select
          aria-label="平台筛选"
          value={platform}
          onChange={(event) => onPlatformChange(event.target.value)}
        >
          <option value="">全部平台</option>
          {platforms.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
      </label>
      <div className="header-account">
        <Link className="header-user" href="/admin" title="设置">
          <ShieldCheck size={16} aria-hidden="true" />
          Admin
        </Link>
        <button type="button" onClick={handleLogout} title="退出登录" aria-label="退出登录">
          <LogOut size={16} aria-hidden="true" />
        </button>
      </div>
    </header>
  );
}
