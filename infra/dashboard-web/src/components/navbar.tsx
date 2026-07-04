"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { MessageSquare, Database, LineChart, Settings, BookOpen, ExternalLink } from "lucide-react";
import { cn } from "@/lib/utils";
import { useLegacySkin } from "@/components/app-providers";

const ASSAY_URL = process.env.NEXT_PUBLIC_ASSAY_WEB_URL ?? "https://assay.example.com";

const NAV_ITEMS = [
  { href: "/", label: "Chat", icon: MessageSquare },
  { href: "/data", label: "Data", icon: Database },
  { href: "/pmb", label: "PMB", icon: LineChart },
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/doc", label: "Doc", icon: BookOpen },
];

export function Navbar() {
  const legacy = useLegacySkin();
  const pathname = usePathname();
  // Active state compares against the path with any /legacy prefix stripped; links keep
  // the user on the current skin by re-adding the prefix in legacy mode.
  const base = pathname.replace(/^\/legacy(?=\/|$)/, "") || "/";
  const withSkin = (href: string) => (legacy ? (href === "/" ? "/legacy" : `/legacy${href}`) : href);

  return (
    <header className="site-nav mb-6 rounded-2xl border bg-white/80 p-4 backdrop-blur shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="nav-logo flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-emerald-500 text-white font-bold">
            Q
          </div>
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground/70 leading-tight">
              QFinZero
            </p>
            <h1 className="text-xl font-bold text-primary tracking-tight leading-none">Console</h1>
          </div>
        </div>
        <nav className="flex flex-wrap items-center gap-1.5">
          {NAV_ITEMS.map((item) => {
            const isActive = item.href === "/" ? base === "/" : base.startsWith(item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={withSkin(item.href)}
                className={cn(
                  "flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-medium transition-all duration-200",
                  isActive
                    ? "bg-primary text-primary-foreground shadow-md"
                    : "bg-transparent text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                )}
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </Link>
            );
          })}
          <a
            href={ASSAY_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-medium text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-all duration-200"
          >
            Assay
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        </nav>
      </div>
    </header>
  );
}
