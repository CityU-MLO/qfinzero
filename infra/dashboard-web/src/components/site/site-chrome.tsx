"use client";

import Link from "next/link";
import { ArrowRight, Github } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { useMe } from "@/components/user-menu";

const REPO = process.env.NEXT_PUBLIC_REPO_URL ?? "https://github.com/CityU-MLO/qfinzero";

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <Link href="/" className="flex shrink-0 items-center gap-2" aria-label="QFinZero home">
      <span
        className={`nav-logo flex items-center justify-center rounded-md bg-primary font-semibold text-primary-foreground ${
          compact ? "h-6 w-6 text-[13px]" : "h-7 w-7 text-sm"
        }`}
      >
        Q
      </span>
      <span className={`font-semibold tracking-tight text-foreground ${compact ? "text-[15px]" : "text-base"}`}>QFinZero</span>
    </Link>
  );
}

export function SiteHeader() {
  const { data: me, isFetched } = useMe();
  return (
    <header className="sticky top-0 z-30 border-b bg-card">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-4 px-4 md:px-6">
        <Logo />
        <nav className="hidden items-center gap-6 text-sm text-muted-foreground md:flex">
          <Link href="/#platform" className="hover:text-foreground">Platform</Link>
          <Link href="/#time-lock" className="hover:text-foreground">Time lock</Link>
          <Link href="/#research" className="hover:text-foreground">Research</Link>
          <Link href="/#quickstart" className="hover:text-foreground">Quick start</Link>
          <a href={REPO} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 hover:text-foreground">
            <Github className="h-4 w-4" /> GitHub
          </a>
        </nav>
        <div className="flex items-center gap-2">
          {isFetched && me ? (
            <Link href="/chat" className={buttonVariants({ size: "sm" })}>
              Open console <ArrowRight />
            </Link>
          ) : (
            <Link href="/login" className={buttonVariants({ size: "sm", variant: "outline" })}>
              Sign in
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="mt-20 border-t bg-card">
      <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-10 text-sm text-muted-foreground md:flex-row md:items-center md:justify-between md:px-6">
        <div className="space-y-2">
          <Logo />
          <p>Open source under the MIT license. Built at City University of Hong Kong.</p>
        </div>
        <div className="flex flex-wrap gap-5">
          <a href={REPO} target="_blank" rel="noopener noreferrer" className="hover:text-foreground">Source</a>
          <a href={`${REPO}/blob/main/docs/en/data-adapters.md`} target="_blank" rel="noopener noreferrer" className="hover:text-foreground">Data adapters</a>
          <a href={`${REPO}/blob/main/docs/upq/README.md`} target="_blank" rel="noopener noreferrer" className="hover:text-foreground">API reference</a>
          <Link href="/login" className="hover:text-foreground">Sign in</Link>
        </div>
      </div>
    </footer>
  );
}
