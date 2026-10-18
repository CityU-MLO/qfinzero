"use client";

import * as React from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Streamdown } from "streamdown";
import "streamdown/styles.css";
import { ArrowLeft, ArrowRight, ExternalLink, Loader2, Search } from "lucide-react";

import { useLocale, useT } from "@/components/locale-provider";
import { Alert } from "@/components/ui/alert";
import { headings, slugify, type DocContent, type DocIndex } from "@/lib/docs";
import { cn } from "@/lib/utils";

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}

function textOf(node: React.ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (React.isValidElement<{ children?: React.ReactNode }>(node)) return textOf(node.props.children);
  return "";
}

function heading(Tag: "h2" | "h3") {
  return function H({ children, className }: { children?: React.ReactNode; className?: string }) {
    return (
      <Tag id={slugify(textOf(children))} className={cn("scroll-mt-20", className)}>
        {children}
      </Tag>
    );
  };
}

function DocLink({ href, children }: { href?: string; children?: React.ReactNode }) {
  const cls = "font-medium text-primary underline-offset-2 hover:underline";
  if (href && (href.startsWith("/docs") || href.startsWith("#"))) {
    return <Link href={href} className={cls}>{children}</Link>;
  }
  return <a href={href} target="_blank" rel="noopener noreferrer" className={cls}>{children}</a>;
}

const COMPONENTS = { h2: heading("h2"), h3: heading("h3"), a: DocLink };

export function DocsHub({ slug }: { slug: string }) {
  const { locale } = useLocale();
  const t = useT();
  const [q, setQ] = React.useState("");
  const index = useQuery({ queryKey: ["docs", "index"], queryFn: () => getJson<DocIndex>("/api/docs") });
  const page = useQuery({
    queryKey: ["docs", slug, locale],
    queryFn: () => getJson<DocContent>(`/api/docs?slug=${encodeURIComponent(slug)}&lang=${locale}`),
  });
  const L = (x: { en: string; zh: string }) => (locale === "zh" ? x.zh : x.en);
  const toc = React.useMemo(() => headings(page.data?.content ?? ""), [page.data?.content]);

  // scroll to #anchor once the page has rendered
  React.useEffect(() => {
    if (!page.data || !window.location.hash) return;
    const el = document.getElementById(decodeURIComponent(window.location.hash.slice(1)));
    if (el) el.scrollIntoView();
  }, [page.data]);

  const needle = q.trim().toLowerCase();
  const sections = (index.data?.sections ?? [])
    .map((s) => ({
      ...s,
      pages: s.pages.filter(
        (p) => !needle || p.title.en.toLowerCase().includes(needle) || p.title.zh.includes(needle) || p.slug.includes(needle),
      ),
    }))
    .filter((s) => s.pages.length);

  return (
    <div className="mx-auto flex max-w-7xl gap-8 px-4 pb-16 pt-6 md:px-6">
      {/* index */}
      <aside className="hidden w-56 shrink-0 md:block">
        <div className="sticky top-16 max-h-[calc(100vh-5rem)] overflow-y-auto pb-6">
          <label className="relative mb-4 block">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t("Filter pages", "筛选页面")}
              className="w-full rounded-md border border-input bg-card py-1.5 pl-8 pr-2 text-[13px] outline-none focus:border-ring focus:ring-2 focus:ring-ring/20"
            />
          </label>
          <nav className="space-y-5" aria-label={t("Documentation", "文档")}>
            {sections.map((s) => (
              <div key={s.id}>
                <p className="mb-1.5 px-2 text-xs font-semibold text-muted-foreground">{L(s.title)}</p>
                <ul className="space-y-px">
                  {s.pages.map((p) => (
                    <li key={p.slug}>
                      <Link
                        href={`/docs/${p.slug}`}
                        aria-current={p.slug === slug ? "page" : undefined}
                        className={cn(
                          "block rounded-md px-2 py-1 text-[13px] transition-colors",
                          p.slug === slug
                            ? "bg-secondary font-medium text-foreground"
                            : "text-muted-foreground hover:bg-accent hover:text-foreground",
                        )}
                      >
                        {L(p.title)}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>
        </div>
      </aside>

      {/* page */}
      <article className="min-w-0 flex-1">
        {/* compact page picker on small screens */}
        <select
          className="mb-4 w-full rounded-md border border-input bg-card px-2 py-1.5 text-sm md:hidden"
          value={slug}
          onChange={(e) => (window.location.href = `/docs/${e.target.value}`)}
        >
          {(index.data?.sections ?? []).map((s) => (
            <optgroup key={s.id} label={L(s.title)}>
              {s.pages.map((p) => (
                <option key={p.slug} value={p.slug}>{L(p.title)}</option>
              ))}
            </optgroup>
          ))}
        </select>

        {page.isLoading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> {t("Loading…", "加载中…")}
          </div>
        )}
        {page.isError && (
          <Alert variant="error" title={t("Page not found", "页面不存在")}>
            <Link href="/docs" className="text-primary underline">{t("Back to the documentation", "返回文档首页")}</Link>
          </Alert>
        )}
        {page.data && (
          <>
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
              <span>
                {sections.find((s) => s.pages.some((p) => p.slug === slug)) &&
                  L(sections.find((s) => s.pages.some((p) => p.slug === slug))!.title)}
              </span>
              <a href={page.data.source} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 hover:text-foreground">
                {t("View source", "查看源文件")} <ExternalLink className="h-3 w-3" />
              </a>
            </div>
            {page.data.fallback && (
              <Alert variant="info" className="mb-4">
                {t("This page is not translated yet; showing the English version.", "此页面暂无中文版本，以下显示英文原文。")}
              </Alert>
            )}
            <div className="doc-body rounded-lg border bg-card px-5 py-6 md:px-8">
              <Streamdown
                mode="static"
                components={COMPONENTS}
                controls={{ table: false, code: true, mermaid: false }}
                linkSafety={{ enabled: false }}
              >
                {page.data.content}
              </Streamdown>
            </div>
            <div className="mt-6 grid gap-3 sm:grid-cols-2">
              {page.data.prev ? (
                <Link href={`/docs/${page.data.prev.slug}`} className="rounded-md border bg-card px-4 py-3 text-sm hover:border-primary/40">
                  <span className="flex items-center gap-1 text-xs text-muted-foreground"><ArrowLeft className="h-3 w-3" /> {t("Previous", "上一篇")}</span>
                  <span className="font-medium">{L(page.data.prev.title)}</span>
                </Link>
              ) : <span />}
              {page.data.next && (
                <Link href={`/docs/${page.data.next.slug}`} className="rounded-md border bg-card px-4 py-3 text-right text-sm hover:border-primary/40">
                  <span className="flex items-center justify-end gap-1 text-xs text-muted-foreground">{t("Next", "下一篇")} <ArrowRight className="h-3 w-3" /></span>
                  <span className="font-medium">{L(page.data.next.title)}</span>
                </Link>
              )}
            </div>
          </>
        )}
      </article>

      {/* on this page */}
      {toc.length > 2 && (
        <aside className="hidden w-48 shrink-0 xl:block">
          <div className="sticky top-16 max-h-[calc(100vh-5rem)] overflow-y-auto">
            <p className="mb-2 text-xs font-semibold text-muted-foreground">{t("On this page", "本页内容")}</p>
            <ul className="space-y-1 border-l text-[13px]">
              {toc.map((h, i) => (
                <li key={`${h.id}-${i}`}>
                  <a
                    href={`#${h.id}`}
                    className={cn(
                      "-ml-px block border-l border-transparent py-0.5 text-muted-foreground hover:border-foreground/40 hover:text-foreground",
                      h.level === 3 ? "pl-6" : "pl-3",
                    )}
                  >
                    {h.text}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </aside>
      )}
    </div>
  );
}
