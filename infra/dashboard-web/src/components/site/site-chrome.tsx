"use client";

import Link from "next/link";
import { ArrowRight, Github } from "lucide-react";

import { LanguageToggle, useT } from "@/components/locale-provider";
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
  const t = useT();
  return (
    <header className="sticky top-0 z-30 border-b bg-card">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-4 px-4 md:px-6">
        <Logo />
        <nav className="hidden items-center gap-6 text-sm text-muted-foreground md:flex">
          <Link href="/#platform" className="hover:text-foreground">{t("Platform", "平台")}</Link>
          <Link href="/#time-lock" className="hover:text-foreground">{t("Time lock", "时间锁")}</Link>
          <Link href="/#research" className="hover:text-foreground">{t("Research", "研究")}</Link>
          <Link href="/#quickstart" className="hover:text-foreground">{t("Quick start", "快速开始")}</Link>
          <Link href="/docs" className="hover:text-foreground">{t("Docs", "文档")}</Link>
          <a href={REPO} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 hover:text-foreground">
            <Github className="h-4 w-4" /> GitHub
          </a>
        </nav>
        <div className="flex items-center gap-2">
          <LanguageToggle />
          {isFetched && me ? (
            <Link href="/chat" className={buttonVariants({ size: "sm" })}>
              {t("Open console", "进入控制台")} <ArrowRight />
            </Link>
          ) : (
            <Link href="/login" className={buttonVariants({ size: "sm", variant: "outline" })}>
              {t("Sign in", "登录")}
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}

export function SiteFooter() {
  const t = useT();
  return (
    <footer className="mt-20 border-t bg-card">
      <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-10 text-sm text-muted-foreground md:flex-row md:items-center md:justify-between md:px-6">
        <div className="space-y-2">
          <Logo />
          <p>{t("Open source under the MIT license. Built at City University of Hong Kong.", "以 MIT 许可证开源，由香港城市大学开发。")}</p>
        </div>
        <div className="flex flex-wrap gap-5">
          <a href={REPO} target="_blank" rel="noopener noreferrer" className="hover:text-foreground">{t("Source", "源代码")}</a>
          <Link href="/docs" className="hover:text-foreground">{t("Documentation", "文档")}</Link>
          <Link href="/docs/mcp-tools" className="hover:text-foreground">{t("MCP tools", "MCP 工具")}</Link>
          <Link href="/login" className="hover:text-foreground">{t("Sign in", "登录")}</Link>
        </div>
      </div>
    </footer>
  );
}
