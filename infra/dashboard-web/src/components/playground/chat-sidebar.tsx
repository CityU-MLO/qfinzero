"use client";

import { useMemo, useState } from "react";
import { Check, Loader2, MessageSquarePlus, Pencil, Search, Trash2, X } from "lucide-react";

import { useT } from "@/components/locale-provider";
import type { ThreadSummary } from "@/lib/chat-api";
import { cn } from "@/lib/utils";

function bucket(ts: number): "today" | "yesterday" | "week" | "older" {
  const d = new Date(ts * 1000);
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  if (d.getTime() >= start) return "today";
  if (d.getTime() >= start - 86_400_000) return "yesterday";
  if (d.getTime() >= start - 7 * 86_400_000) return "week";
  return "older";
}

export function ChatSidebar({ threads, activeId, loading, onSelect, onNew, onDelete, onRename, query, onQuery }: {
  threads: ThreadSummary[];
  activeId: string | null;
  loading: boolean;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void;
  query: string;
  onQuery: (q: string) => void;
}) {
  const t = useT();
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [confirm, setConfirm] = useState<string | null>(null);

  const groups = useMemo(() => {
    const labels = { today: t("Today", "今天"), yesterday: t("Yesterday", "昨天"), week: t("Previous 7 days", "过去 7 天"), older: t("Older", "更早") };
    const out: { key: string; label: string; items: ThreadSummary[] }[] = [];
    for (const th of threads) {
      const k = bucket(th.updated_at);
      let g = out.find((x) => x.key === k);
      if (!g) out.push((g = { key: k, label: labels[k], items: [] }));
      g.items.push(th);
    }
    return out;
  }, [threads, t]);

  return (
    <aside className="flex w-64 shrink-0 flex-col border-r bg-muted/30">
      <div className="flex flex-col gap-2 p-3">
        <button onClick={onNew}
          className="flex items-center gap-2 rounded-md border bg-card px-3 py-2 text-sm font-medium text-foreground transition hover:bg-muted">
          <MessageSquarePlus className="h-4 w-4" /> {t("New chat", "新对话")}
        </button>
        <label className="flex items-center gap-1.5 rounded-md border bg-card px-2 py-1.5">
          <Search className="h-3.5 w-3.5 text-muted-foreground" />
          <input value={query} onChange={(e) => onQuery(e.target.value)} placeholder={t("Search chats", "搜索对话")}
            className="w-full bg-transparent text-[13px] outline-none" />
        </label>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {loading && !threads.length && <div className="flex justify-center py-6"><Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /></div>}
        {!loading && !threads.length && (
          <p className="px-2 py-6 text-center text-[12px] text-muted-foreground">
            {query ? t("No matching chats.", "没有匹配的对话。") : t("No chats yet.", "还没有对话。")}
          </p>
        )}
        {groups.map((g) => (
          <div key={g.key} className="mb-2">
            <div className="px-2 pb-1 pt-2 text-[11px] font-medium text-muted-foreground">{g.label}</div>
            {g.items.map((th) => {
              const active = th.id === activeId;
              if (editing === th.id) {
                return (
                  <form key={th.id} className="flex items-center gap-1 rounded-md bg-card px-1 py-1"
                    onSubmit={(e) => { e.preventDefault(); if (draft.trim()) onRename(th.id, draft.trim()); setEditing(null); }}>
                    <input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)}
                      onKeyDown={(e) => e.key === "Escape" && setEditing(null)}
                      className="min-w-0 flex-1 rounded border px-1.5 py-0.5 text-[13px] outline-none" />
                    <button type="submit" className="p-0.5 text-success"><Check className="h-3.5 w-3.5" /></button>
                    <button type="button" onClick={() => setEditing(null)} className="p-0.5 text-muted-foreground"><X className="h-3.5 w-3.5" /></button>
                  </form>
                );
              }
              return (
                <div key={th.id} className={cn("group flex items-center gap-1 rounded-md px-2 py-1.5 text-[13px]",
                  active ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground")}>
                  <button onClick={() => onSelect(th.id)} onDoubleClick={() => { setEditing(th.id); setDraft(th.title); }}
                    className="flex min-w-0 flex-1 items-center gap-1.5 text-left">
                    {th.running && <Loader2 className="h-3 w-3 shrink-0 animate-spin text-warning" />}
                    <span className="truncate">{th.title || t("New chat", "新对话")}</span>
                  </button>
                  {confirm === th.id ? (
                    <span className="flex items-center gap-0.5">
                      <button onClick={() => { onDelete(th.id); setConfirm(null); }} className="rounded px-1 text-[11px] text-destructive hover:bg-destructive/10">
                        {t("Delete", "删除")}
                      </button>
                      <button onClick={() => setConfirm(null)} className="p-0.5"><X className="h-3 w-3" /></button>
                    </span>
                  ) : (
                    <span className="hidden items-center gap-0.5 group-hover:flex">
                      <button onClick={() => { setEditing(th.id); setDraft(th.title); }} className="rounded p-0.5 hover:text-foreground"
                        title={t("Rename", "重命名")} aria-label={t("Rename", "重命名")}><Pencil className="h-3 w-3" /></button>
                      <button onClick={() => setConfirm(th.id)} className="rounded p-0.5 hover:text-destructive"
                        title={t("Delete", "删除")} aria-label={t("Delete", "删除")}><Trash2 className="h-3 w-3" /></button>
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </aside>
  );
}
