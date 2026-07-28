"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, BellRing, Hash, Settings, UsersRound } from "lucide-react";

const navItems = [
  { label: "总览", href: "/", icon: BarChart3 },
  { label: "KOL", href: "/kols", icon: UsersRound },
  { label: "标的", href: "/assets", icon: Hash },
  { label: "设置", href: "/admin", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="dashboard-sidebar" aria-label="主导航">
      <Link className="terminal-brand" href="/">
        <span>
          <BellRing size={18} aria-hidden="true" />
        </span>
        <div>
          <strong>KOL Intel</strong>
          <small>金融情报流</small>
        </div>
      </Link>
      <nav className="sidebar-nav">
        {navItems.map((item) => {
          const Icon = item.icon;
          const active =
            item.href === "/"
              ? pathname === "/"
              : pathname.startsWith(item.href);
          return (
            <Link className={active ? "active" : ""} href={item.href} key={item.label}>
              <Icon size={17} aria-hidden="true" />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="sidebar-status">
        <span />
        <div>
          <strong>分钟级监听</strong>
          <small>X / Binance / A股</small>
        </div>
      </div>
    </aside>
  );
}
