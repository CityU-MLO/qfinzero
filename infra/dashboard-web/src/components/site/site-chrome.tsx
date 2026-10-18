"use client";

import Link from "next/link";
import { ArrowRight, Github } from "lucide-react";

import { useMe } from "@/components/user-menu";

const REPO = process.env.NEXT_PUBLIC_REPO_URL ?? "https://github.com/CityU-MLO/qfinzero";

export function Logo() {
  return (
    <Link href="/" className="flex items-center gap-2.5" aria-label="QFinZero home">
      <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-cyan-600 to-emerald-500 text-lg font-bold text-white shadow-sm">
        Q
      </span>
      <span className="text-lg font-bold tracking-tight text-foreground">QFinZero</span>
    </Link>
  );
}

export function SiteHeader() {
  const { data: me, isFetched } = useMe();
  return (
    <header className="sticky top-0 z-30 border-b border-white/60 bg-background/80 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-4 md:px-6">
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
            <Link href="/chat" className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground shadow hover:bg-primary/90">
              Open console <ArrowRight className="h-4 w-4" />
            </Link>
          ) : (
            <Link href="/login" className="inline-flex h-9 items-center rounded-lg border bg-white px-4 text-sm font-medium shadow-sm hover:bg-accent">
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
    <footer className="mt-24 border-t bg-white/50">
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
