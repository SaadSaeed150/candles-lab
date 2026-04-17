"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  FlaskConical,
  History,
  LineChart,
  LogOut,
  User,
} from "lucide-react";
import { useAuth } from "@/lib/auth";
import { clsx } from "clsx";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/backtest", label: "Backtest", icon: FlaskConical },
  { href: "/runs", label: "Runs", icon: History },
  { href: "/market", label: "Market Data", icon: LineChart },
];

export default function Sidebar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();

  return (
    <aside className="fixed left-0 top-0 z-40 flex h-screen w-60 flex-col border-r border-[var(--color-border)] bg-[var(--color-bg-secondary)]">
      {/* Logo */}
      <div className="flex h-16 items-center gap-2 border-b border-[var(--color-border)] px-5">
        <div className="h-8 w-8 rounded-lg bg-[var(--color-accent)] flex items-center justify-center">
          <LineChart className="h-4 w-4 text-white" />
        </div>
        <span className="text-lg font-semibold tracking-tight">TradeLab</span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-1 px-3 py-4">
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || (href !== "/" && pathname.startsWith(href));
          return (
            <Link
              key={href}
              href={href}
              className={clsx(
                "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                active
                  ? "bg-[var(--color-accent)]/10 text-[var(--color-accent)]"
                  : "text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-primary)]"
              )}
            >
              <Icon className="h-4 w-4" />
              {label}
            </Link>
          );
        })}
      </nav>

      {/* User */}
      <div className="border-t border-[var(--color-border)] px-3 py-3">
        {user ? (
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--color-bg-hover)]">
                <User className="h-4 w-4 text-[var(--color-text-secondary)]" />
              </div>
              <span className="text-sm text-[var(--color-text-secondary)]">
                {user.username}
              </span>
            </div>
            <button
              onClick={logout}
              className="rounded-md p-1.5 text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-red)]"
              title="Logout"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        ) : (
          <Link
            href="/login"
            className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)]"
          >
            <User className="h-4 w-4" />
            Sign in
          </Link>
        )}
      </div>
    </aside>
  );
}
