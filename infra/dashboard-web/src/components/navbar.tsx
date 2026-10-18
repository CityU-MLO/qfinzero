"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BookOpen, CalendarDays, Database, LineChart, MessageSquare, Newspaper, Settings } from "lucide-react";

import { useLegacySkin } from "@/components/app-providers";
import { Logo } from "@/components/site/site-chrome";
import { UserMenu, useMe } from "@/components/user-menu";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/chat", label: "Chat", icon: MessageSquare, admin: false },
  { href: "/broker", label: "Broker", icon: LineChart, admin: false },
  { href: "/news", label: "News", icon: Newspaper, admin: false },
  { href: "/calendar", label: "Calendar", icon: CalendarDays, admin: false },
  { href: "/data", label: "Data", icon: Database, admin: true },
  { href: "/doc", label: "Docs", icon: BookOpen, admin: false },
];

export function Navbar() {
  const legacy = useLegacySkin();
  const pathname = usePathname();
  const { data: me } = useMe();
  // Without the hub (no /auth) everything is shown; with it, admin-only links need admin.
  const items = NAV_ITEMS.filter((i) => !i.admin || !me || me.role === "admin");
  // Active state compares against the path with any /legacy prefix stripped; links keep
  // the user on the current skin by re-adding the prefix in legacy mode.
  const base = pathname.replace(/^\/legacy(?=\/|$)/, "") || "/";
  const withSkin = (href: string) => (legacy ? (href === "/chat" ? "/legacy" : `/legacy${href}`) : href);
  const active = (href: string) => (href === "/chat" ? base === "/chat" || base === "/" : base.startsWith(href));

  return (
    <header className="site-nav sticky top-0 z-40 border-b bg-card">
      <div className="mx-auto flex h-12 max-w-7xl items-center gap-6 px-4 md:px-6">
        <Logo compact />
        <nav className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto" aria-label="Console">
          {items.map((item) => {
            const Icon = item.icon;
            const on = active(item.href);
            return (
              <Link
                key={item.href}
                href={withSkin(item.href)}
                aria-current={on ? "page" : undefined}
                className={cn(
                  "flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors",
                  on ? "nav-active bg-secondary text-foreground" : "text-muted-foreground hover:bg-accent hover:text-foreground",
                )}
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="flex items-center gap-1">
          <Link
            href={withSkin("/settings")}
            title="Model providers and preferences"
            aria-current={active("/settings") ? "page" : undefined}
            className={cn(
              "flex h-8 w-8 items-center justify-center rounded-md transition-colors",
              active("/settings") ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-accent hover:text-foreground",
            )}
          >
            <Settings className="h-4 w-4" />
            <span className="sr-only">Settings</span>
          </Link>
          <UserMenu />
        </div>
      </div>
    </header>
  );
}
