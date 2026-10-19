"use client";

// The documentation hub: /docs (home), /docs/<guide>, /docs/api[/<service>[/<endpoint>]],
// /docs/mcp[/<tool>]. Guides are the repository's markdown (docs/index.json);
// the references are generated (docs/api/reference.json).

import * as React from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, BookOpen, ExternalLink, Library, Loader2, Rocket, Server } from "lucide-react";

import { useLocale, useT } from "@/components/locale-provider";
import { Alert } from "@/components/ui/alert";
import { DocMarkdown, Toc } from "@/components/docs/markdown";
import { DocsHome } from "@/components/docs/home";
import { ApiHome, ApiNav, EndpointPage, McpHome, McpNav, ServicePage, ToolPage } from "@/components/docs/reference";
import { Breadcrumbs, DocsShell, NavGroup, NavItem, type DocsTab } from "@/components/docs/shell";
import { headings, type ApiReference, type DocContent, type DocIndex } from "@/lib/docs";

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}

const SECTION_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  start: Rocket, guides: BookOpen, reference: Library, operations: Server,
};

function useIndex() {
  return useQuery({ queryKey: ["docs", "index"], queryFn: () => getJson<DocIndex>("/api/docs"), staleTime: 60_000 });
}

function useReference() {
  return useQuery({ queryKey: ["docs", "reference"], queryFn: () => getJson<ApiReference>("/api/docs?ref=1"), staleTime: 60_000 });
}

function GuideNav({ index, slug }: { index?: DocIndex; slug?: string }) {
  const { locale } = useLocale();
  const L = (x: { en: string; zh: string }) => (locale === "zh" ? x.zh : x.en);
  return (
    <nav>
      {(index?.sections ?? []).map((s) => (
        <NavGroup key={s.id} title={L(s.title)} icon={SECTION_ICON[s.id]} active={s.pages.some((p) => p.slug === slug)}>
          {s.pages.map((p) => <NavItem key={p.slug} href={`/docs/${p.slug}`} active={p.slug === slug}>{L(p.title)}</NavItem>)}
        </NavGroup>
      ))}
    </nav>
  );
}

function Loading() {
  const t = useT();
  return <div className="flex items-center gap-2 py-10 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />{t("Loading…", "加载中…")}</div>;
}

function NotFound() {
  const t = useT();
  return (
    <Alert variant="error" title={t("Page not found", "页面不存在")}>
      <Link href="/docs" className="text-primary underline">{t("Back to the documentation", "返回文档首页")}</Link>
    </Alert>
  );
}

function GuidePage({ slug }: { slug: string }) {
  const { locale } = useLocale();
  const t = useT();
  const index = useIndex();
  const page = useQuery({
    queryKey: ["docs", slug, locale],
    queryFn: () => getJson<DocContent>(`/api/docs?slug=${encodeURIComponent(slug)}&lang=${locale}`),
  });
  const L = (x: { en: string; zh: string }) => (locale === "zh" ? x.zh : x.en);
  const toc = React.useMemo(() => headings(page.data?.content ?? ""), [page.data?.content]);
  const section = index.data?.sections.find((s) => s.pages.some((p) => p.slug === slug));

  React.useEffect(() => {
    if (!page.data || !window.location.hash) return;
    const el = document.getElementById(decodeURIComponent(window.location.hash.slice(1)));
    if (el) requestAnimationFrame(() => el.scrollIntoView());
  }, [page.data]);

  const tab: DocsTab = slug === "changelog" ? "changelog" : "guides";
  return (
    <DocsShell tab={tab} nav={<GuideNav index={index.data} slug={slug} />}
               rail={toc.length > 1 ? <Toc items={toc} title={t("On this page", "本页内容")} /> : undefined}>
      {page.isLoading && <Loading />}
      {page.isError && <NotFound />}
      {page.data && (
        <>
          <div className="flex items-start justify-between gap-4">
            <Breadcrumbs items={[{ label: t("Docs", "文档"), href: "/docs" }, ...(section ? [{ label: L(section.title) }] : []), { label: L(page.data.title) }]} />
            <a href={page.data.source} target="_blank" rel="noopener noreferrer"
               className="inline-flex shrink-0 items-center gap-1 text-[12.5px] text-muted-foreground hover:text-foreground">
              {t("View source", "查看源文件")} <ExternalLink className="h-3 w-3" />
            </a>
          </div>
          {page.data.fallback && (
            <Alert variant="info" className="mb-5">{t("This page is not translated yet; showing the English version.", "此页面暂无中文版本，以下显示英文原文。")}</Alert>
          )}
          <DocMarkdown>{page.data.content}</DocMarkdown>
          <div className="mt-14 grid gap-3 border-t pt-6 sm:grid-cols-2">
            {page.data.prev ? (
              <Link href={`/docs/${page.data.prev.slug}`} className="group rounded-xl border px-4 py-3 transition-colors hover:border-primary/40">
                <span className="flex items-center gap-1 text-xs text-muted-foreground"><ArrowLeft className="h-3 w-3" /> {t("Previous", "上一篇")}</span>
                <span className="font-medium group-hover:text-primary">{L(page.data.prev.title)}</span>
              </Link>
            ) : <span />}
            {page.data.next && (
              <Link href={`/docs/${page.data.next.slug}`} className="group rounded-xl border px-4 py-3 text-right transition-colors hover:border-primary/40">
                <span className="flex items-center justify-end gap-1 text-xs text-muted-foreground">{t("Next", "下一篇")} <ArrowRight className="h-3 w-3" /></span>
                <span className="font-medium group-hover:text-primary">{L(page.data.next.title)}</span>
              </Link>
            )}
          </div>
        </>
      )}
    </DocsShell>
  );
}

function ApiPages({ service, endpoint }: { service?: string; endpoint?: string }) {
  const ref = useReference();
  const svc = ref.data?.services.find((s) => s.id === service);
  const ep = svc?.endpoints.find((e) => e.id === endpoint);
  const nav = <ApiNav ref_={ref.data} service={service} endpoint={endpoint} />;
  return (
    <DocsShell tab="api" nav={nav} wide={!!ep}>
      {ref.isLoading ? <Loading /> : !service ? <ApiHome ref_={ref.data} />
        : !svc || (endpoint && !ep) ? <NotFound /> : ep ? <EndpointPage svc={svc} ep={ep} /> : <ServicePage svc={svc} />}
    </DocsShell>
  );
}

function McpPages({ tool }: { tool?: string }) {
  const ref = useReference();
  const x = ref.data?.mcp.find((m) => m.name === tool);
  return (
    <DocsShell tab="mcp" nav={<McpNav ref_={ref.data} tool={tool} />} wide={!!x}>
      {ref.isLoading ? <Loading /> : !tool ? <McpHome ref_={ref.data} /> : x ? <ToolPage tool={x} /> : <NotFound />}
    </DocsShell>
  );
}

function Home() {
  const ref = useReference();
  return (
    <DocsShell tab="home" wide>
      <div className="mx-auto max-w-6xl"><DocsHome ref_={ref.data} /></div>
    </DocsShell>
  );
}

export function DocsHub({ slug }: { slug: string[] }) {
  const [head, a, b] = slug;
  if (!head) return <Home />;
  if (head === "api") return <ApiPages service={a} endpoint={b} />;
  if (head === "mcp") return <McpPages tool={a} />;
  return <GuidePage slug={head} />;
}
