"use client";

// Frame of the documentation hub: a docs bar (sections + search) under the
// site or console bar, a left navigation, the page and an optional right rail.

import * as React from "react";
import Link from "next/link";
import { ChevronDown, Menu, Search, X } from "lucide-react";

import { useT } from "@/components/locale-provider";
import { SearchDialog, useSearchShortcut } from "@/components/docs/search";
import { cn } from "@/lib/utils";

export type DocsTab = "home" | "guides" | "api" | "mcp" | "changelog";

const BAR = "44px";

const SearchContext = React.createContext<() => void>(() => {});
/** Open the docs search dialog from anywhere inside the shell. */
export const useDocsSearch = () => React.useContext(SearchContext);

export function DocsShell({ tab, nav, rail, children, wide }: {
  tab: DocsTab;
  nav?: React.ReactNode;
  rail?: React.ReactNode;
  children: React.ReactNode;
  wide?: boolean;
}) {
  const t = useT();
  const [search, setSearch] = React.useState(false);
  const [drawer, setDrawer] = React.useState(false);
  const openSearch = React.useCallback(() => setSearch(true), []);
  useSearchShortcut(openSearch);
  const tabs: { id: DocsTab; href: string; label: string }[] = [
    { id: "home", href: "/docs", label: t("Home", "首页") },
    { id: "guides", href: "/docs/getting-started", label: t("Guides", "指南") },
    { id: "api", href: "/docs/api", label: t("API reference", "API 参考") },
    { id: "mcp", href: "/docs/mcp", label: t("MCP tools", "MCP 工具") },
    { id: "changelog", href: "/docs/changelog", label: t("Changelog", "更新日志") },
  ];
  return (
    <SearchContext.Provider value={openSearch}>
    <div style={{ "--docs-bar": BAR } as React.CSSProperties}>
      <div className="sticky z-30 border-b bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/80" style={{ top: "var(--nav-h, 48px)" }}>
        <div className="mx-auto flex max-w-[90rem] items-center gap-2 px-4 md:px-6" style={{ height: BAR }}>
          {nav && (
            <button className="-ml-1 rounded-md p-1.5 text-muted-foreground hover:bg-accent lg:hidden" onClick={() => setDrawer(true)}
                    aria-label={t("Open navigation", "打开导航")}>
              <Menu className="h-4 w-4" />
            </button>
          )}
          <nav className="no-scrollbar flex h-full min-w-0 items-stretch gap-1 overflow-x-auto" aria-label={t("Documentation sections", "文档分区")}>
            {tabs.map((x) => (
              <Link key={x.id} href={x.href}
                    className={cn("flex shrink-0 items-center border-b-2 px-2.5 text-[13px] font-medium transition-colors",
                      tab === x.id ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
                {x.label}
              </Link>
            ))}
          </nav>
          <button onClick={openSearch}
                  className="ml-auto flex h-8 shrink-0 items-center gap-2 rounded-lg border bg-background px-2.5 text-[13px] text-muted-foreground hover:border-ring/50 hover:text-foreground sm:w-64">
            <Search className="h-3.5 w-3.5" />
            <span className="hidden flex-1 text-left sm:inline">{t("Search docs…", "搜索文档…")}</span>
            <kbd className="kbd hidden sm:inline-flex">⌘K</kbd>
          </button>
        </div>
      </div>

      <div className={cn("mx-auto flex max-w-[90rem] gap-10 px-4 md:px-6", !nav && "justify-center")}>
        {nav && (
          <aside className="hidden w-64 shrink-0 lg:block">
            <div className="docs-scroll sticky overflow-y-auto py-6 pr-2"
                 style={{ top: "calc(var(--nav-h, 48px) + var(--docs-bar))", maxHeight: "calc(100vh - var(--nav-h, 48px) - var(--docs-bar))" }}>
              {nav}
            </div>
          </aside>
        )}
        <main className={cn("min-w-0 flex-1 py-8", wide ? "" : "max-w-3xl")}>{children}</main>
        {rail && (
          <aside className="hidden w-56 shrink-0 xl:block">
            <div className="docs-scroll sticky overflow-y-auto py-8"
                 style={{ top: "calc(var(--nav-h, 48px) + var(--docs-bar))", maxHeight: "calc(100vh - var(--nav-h, 48px) - var(--docs-bar))" }}>
              {rail}
            </div>
          </aside>
        )}
      </div>

      {drawer && nav && (
        <div className="fixed inset-0 z-50 bg-foreground/25 lg:hidden" onClick={() => setDrawer(false)}>
          <div className="h-full w-72 overflow-y-auto bg-card p-4 shadow-xl" onClick={(e) => {
            e.stopPropagation();
            if ((e.target as HTMLElement).closest("a")) setDrawer(false);
          }}>
            <div className="mb-3 flex justify-end">
              <button className="rounded-md p-1.5 text-muted-foreground hover:bg-accent" onClick={() => setDrawer(false)} aria-label={t("Close", "关闭")}><X className="h-4 w-4" /></button>
            </div>
            {nav}
          </div>
        </div>
      )}
      <SearchDialog open={search} onClose={() => setSearch(false)} />
    </div>
    </SearchContext.Provider>
  );
}

/** A collapsible navigation group. */
export function NavGroup({ title, icon: Icon, children, defaultOpen = true, active }: {
  title: string;
  icon?: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
  defaultOpen?: boolean;
  active?: boolean;
}) {
  const [open, setOpen] = React.useState(defaultOpen || !!active);
  React.useEffect(() => {
    if (active) setOpen(true);
  }, [active]);
  return (
    <div className="mb-4">
      <button onClick={() => setOpen(!open)}
              className="group flex w-full items-center gap-2 px-2 py-1 text-left text-[12px] font-semibold uppercase tracking-wide text-muted-foreground hover:text-foreground">
        {Icon && <Icon className="h-3.5 w-3.5" />}
        <span className="flex-1">{title}</span>
        <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", !open && "-rotate-90")} />
      </button>
      {open && <ul className="mt-1 space-y-px">{children}</ul>}
    </div>
  );
}

export function NavItem({ href, active, children, mono }: { href: string; active?: boolean; children: React.ReactNode; mono?: boolean }) {
  const ref = React.useRef<HTMLAnchorElement>(null);
  React.useEffect(() => {
    if (active) ref.current?.scrollIntoView({ block: "nearest" });
  }, [active]);
  return (
    <li>
      <Link ref={ref} href={href} aria-current={active ? "page" : undefined}
            className={cn("relative flex items-center gap-2 rounded-md px-2 py-[5px] text-[13.5px] leading-snug transition-colors",
              mono && "font-mono text-[12.5px]",
              active ? "bg-primary/[0.08] font-medium text-primary before:absolute before:-left-px before:top-1.5 before:bottom-1.5 before:w-0.5 before:rounded-full before:bg-primary"
                : "text-muted-foreground hover:bg-accent/70 hover:text-foreground")}>
        {children}
      </Link>
    </li>
  );
}

export function Breadcrumbs({ items }: { items: { label: string; href?: string }[] }) {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-1.5 text-[13px] text-muted-foreground">
      {items.map((x, i) => (
        <React.Fragment key={i}>
          {i > 0 && <span className="text-border">/</span>}
          {x.href ? <Link href={x.href} className="hover:text-foreground">{x.label}</Link> : <span className="text-foreground/80">{x.label}</span>}
        </React.Fragment>
      ))}
    </div>
  );
}
