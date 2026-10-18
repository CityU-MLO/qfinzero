"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BookOpen, CalendarDays, Database, Grid3x3, LineChart, MessageSquare, Newspaper, Settings } from "lucide-react";

import { useLegacySkin } from "@/components/app-providers";
import { LanguageToggle, useT } from "@/components/locale-provider";
import { Logo } from "@/components/site/site-chrome";
import { UserMenu, useMe } from "@/components/user-menu";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/chat", label: ["Chat", "对话"], icon: MessageSquare, admin: false },
  { href: "/broker", label: ["Broker", "模拟交易"], icon: LineChart, admin: false },
  { href: "/news", label: ["News", "新闻"], icon: Newspaper, admin: false },
  { href: "/calendar", label: ["Calendar", "日历"], icon: CalendarDays, admin: false },
  { href: "/coverage", label: ["Coverage", "数据覆盖"], icon: Grid3x3, admin: false },
  { href: "/data", label: ["Data", "数据"], icon: Database, admin: true },
  { href: "/docs", label: ["Docs", "文档"], icon: BookOpen, admin: false },
] as const;

export function Navbar() {
  const legacy = useLegacySkin();
  const pathname = usePathname();
  const { data: me } = useMe();
  const t = useT();
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
        <nav className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto" aria-label={t("Console", "控制台")}>
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
                {t(item.label[0], item.label[1])}
              </Link>
            );
          })}
        </nav>
        <div className="flex items-center gap-1">
          <LanguageToggle />
          <Link
            href={withSkin("/settings")}
            title={t("Model providers and preferences", "模型服务与偏好设置")}
            aria-current={active("/settings") ? "page" : undefined}
            className={cn(
              "flex h-8 w-8 items-center justify-center rounded-md transition-colors",
              active("/settings") ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-accent hover:text-foreground",
            )}
          >
            <Settings className="h-4 w-4" />
            <span className="sr-only">{t("Settings", "设置")}</span>
          </Link>
          <UserMenu />
        </div>
      </div>
    </header>
  );
}
