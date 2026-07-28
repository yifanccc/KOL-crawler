"use client";

import Link from "next/link";
import { Activity, Gauge, Search, Settings } from "lucide-react";

export function TopNav() {
  return (
    <header className="top-nav">
      <Link className="brand" href="/" aria-label="KOL Signal Tape 首页">
        <span className="brand-mark">
          <Activity size={20} aria-hidden="true" />
        </span>
        <span>
          <strong>KOL Signal Tape</strong>
          <small>金融交易 KOL 监控</small>
        </span>
      </Link>
      <nav className="nav-links" aria-label="主导航">
        <Link href="/">
          <Gauge size={16} aria-hidden="true" />
          信号
        </Link>
        <Link href="/assets/BTC">
          <Search size={16} aria-hidden="true" />
          标的
        </Link>
        <Link href="/admin">
          <Settings size={16} aria-hidden="true" />
          管理
        </Link>
      </nav>
    </header>
  );
}
