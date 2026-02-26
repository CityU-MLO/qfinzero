"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/", label: "Status" },
  { href: "/news", label: "News Browser" },
  { href: "/calendar", label: "Calendar Browser" },
  { href: "/sanity", label: "Sanity Checks" },
  { href: "/playground", label: "Playground" },
];

export function Navbar() {
  const pathname = usePathname();

  return (
    <header className="mb-6 rounded-2xl border bg-white/80 p-4 backdrop-blur shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground/70 leading-tight">QFinZero</p>
          <h1 className="text-2xl font-bold text-primary tracking-tight">Data Platform Monitor</h1>
        </div>
        <nav className="flex flex-wrap items-center gap-1.5">
          {NAV_ITEMS.map((item) => {
            const isActive = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "rounded-lg px-4 py-2 text-sm font-medium transition-all duration-200",
                  isActive
                    ? "bg-primary text-primary-foreground shadow-md"
                    : "bg-transparent text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                )}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
