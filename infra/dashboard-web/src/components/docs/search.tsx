"use client";

// ⌘K search over every guide section, API endpoint and MCP tool.

import * as React from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, CornerDownLeft, Loader2, Search, SquareFunction, Webhook, X } from "lucide-react";

import { useLocale, useT } from "@/components/locale-provider";
import { excerpt, scoreEntry, type SearchEntry } from "@/lib/docs";
import { cn } from "@/lib/utils";

const ICON = { guide: BookOpen, endpoint: Webhook, tool: SquareFunction } as const;

function Highlight({ text, words }: { text: string; words: string[] }) {
  if (!words.length) return <>{text}</>;
  const re = new RegExp(`(${words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  return <>{text.split(re).map((part, i) => (i % 2 ? <mark key={i} className="rounded-sm bg-primary/15 px-px text-foreground">{part}</mark> : part))}</>;
}

export function useSearchShortcut(open: () => void) {
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
      if ((e.key === "k" && (e.metaKey || e.ctrlKey)) || (e.key === "/" && !typing)) {
        e.preventDefault();
        open();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
}

export function SearchDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useT();
  const { locale } = useLocale();
  const router = useRouter();
  const [q, setQ] = React.useState("");
  const [sel, setSel] = React.useState(0);
  const [kind, setKind] = React.useState<"all" | SearchEntry["kind"]>("all");
  const listRef = React.useRef<HTMLDivElement>(null);
  const idx = useQuery({
    queryKey: ["docs", "search", locale],
    queryFn: async () => (await (await fetch(`/api/docs?search=1&lang=${locale}`)).json()) as { entries: SearchEntry[] },
    enabled: open,
    staleTime: 5 * 60_000,
  });
  const words = React.useMemo(() => q.toLowerCase().split(/\s+/).filter(Boolean), [q]);
  const results = React.useMemo(() => {
    const all = (idx.data?.entries ?? []).filter((e) => kind === "all" || e.kind === kind);
    if (!words.length) return all.filter((e) => e.kind === "guide" && !e.href.includes("#")).slice(0, 12);
    return all
      .map((e) => ({ e, s: scoreEntry(e, words) }))
      .filter((x) => x.s > 0)
      .sort((a, b) => b.s - a.s)
      .slice(0, 40)
      .map((x) => x.e);
  }, [idx.data, words, kind]);

  React.useEffect(() => setSel(0), [q, kind]);
  React.useEffect(() => {
    if (open) setQ("");
  }, [open]);
  React.useEffect(() => {
    listRef.current?.querySelector(`[data-i="${sel}"]`)?.scrollIntoView({ block: "nearest" });
  }, [sel]);

  if (!open) return null;
  const go = (e: SearchEntry | undefined) => {
    if (!e) return;
    onClose();
    router.push(e.href);
  };
  const kinds = [
    { id: "all" as const, label: t("All", "全部") },
    { id: "guide" as const, label: t("Guides", "指南") },
    { id: "endpoint" as const, label: t("API", "API") },
    { id: "tool" as const, label: t("MCP tools", "MCP 工具") },
  ];
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-foreground/25 p-4 pt-[10vh] backdrop-blur-[2px]" onMouseDown={onClose}>
      <div role="dialog" aria-modal="true" aria-label={t("Search documentation", "搜索文档")}
           className="flex max-h-[70vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border bg-card shadow-2xl"
           onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-3 border-b px-4">
          <Search className="h-4 w-4 text-muted-foreground" />
          <input autoFocus value={q} onChange={(e) => setQ(e.target.value)}
                 placeholder={t("Search guides, endpoints and MCP tools", "搜索指南、接口和 MCP 工具")}
                 className="h-12 flex-1 bg-transparent text-[15px] outline-none placeholder:text-muted-foreground"
                 onKeyDown={(e) => {
                   if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(results.length - 1, s + 1)); }
                   else if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(0, s - 1)); }
                   else if (e.key === "Enter") go(results[sel]);
                   else if (e.key === "Escape") onClose();
                 }} />
          <button onClick={onClose} className="rounded-md p-1 text-muted-foreground hover:bg-accent" aria-label={t("Close", "关闭")}><X className="h-4 w-4" /></button>
        </div>
        <div className="flex gap-1 border-b px-3 py-2">
          {kinds.map((k) => (
            <button key={k.id} onClick={() => setKind(k.id)}
                    className={cn("rounded-full px-2.5 py-0.5 text-xs", kind === k.id ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent")}>
              {k.label}
            </button>
          ))}
        </div>
        <div ref={listRef} className="flex-1 overflow-y-auto p-2">
          {idx.isLoading && <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />{t("Loading the index…", "正在加载索引…")}</div>}
          {!idx.isLoading && results.length === 0 && (
            <p className="p-6 text-center text-sm text-muted-foreground">{t(`No results for “${q}”.`, `没有找到“${q}”的结果。`)}</p>
          )}
          {!words.length && results.length > 0 && <p className="px-3 pb-1 pt-2 text-xs font-medium text-muted-foreground">{t("Pages", "页面")}</p>}
          {results.map((e, i) => {
            const Icon = ICON[e.kind];
            return (
              <button key={`${e.href}-${i}`} data-i={i} onMouseMove={() => setSel(i)} onClick={() => go(e)}
                      className={cn("flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-left", i === sel ? "bg-primary/[0.07]" : "")}>
                <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", i === sel ? "text-primary" : "text-muted-foreground")} />
                <span className="min-w-0 flex-1">
                  <span className="block text-[11px] text-muted-foreground">{e.section}</span>
                  <span className={cn("block truncate text-sm font-medium", e.kind !== "guide" && "font-mono text-[13px]")}><Highlight text={e.title} words={words} /></span>
                  {words.length > 0 && e.text && (
                    <span className="mt-0.5 line-clamp-2 block text-xs text-muted-foreground"><Highlight text={excerpt(e.text, words)} words={words} /></span>
                  )}
                </span>
                {i === sel && <CornerDownLeft className="mt-1 h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-4 border-t bg-muted/40 px-4 py-2 text-[11px] text-muted-foreground">
          <span><kbd className="kbd">↑</kbd> <kbd className="kbd">↓</kbd> {t("move", "移动")}</span>
          <span><kbd className="kbd">↵</kbd> {t("open", "打开")}</span>
          <span><kbd className="kbd">esc</kbd> {t("close", "关闭")}</span>
          <span className="ml-auto">{idx.data ? t(`${idx.data.entries.length} entries`, `共 ${idx.data.entries.length} 条`) : ""}</span>
        </div>
      </div>
    </div>
  );
}
