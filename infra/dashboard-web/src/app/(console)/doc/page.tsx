"use client";

import { useEffect, useState } from "react";
import { Streamdown } from "streamdown";
import "streamdown/styles.css";
import { FileText, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

const PREFERRED = ["docs/en/getting-started.md", "README.md"];

export default function DocPage() {
  const [docs, setDocs] = useState<string[]>([]);
  const [active, setActive] = useState<string>("");
  const [content, setContent] = useState<string>("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch("/api/docs")
      .then((r) => r.json())
      .then((d: { docs: string[] }) => {
        setDocs(d.docs ?? []);
        const first = PREFERRED.find((p) => d.docs?.includes(p)) ?? d.docs?.[0];
        if (first) setActive(first);
      })
      .catch(() => setDocs([]));
  }, []);

  useEffect(() => {
    if (!active) return;
    setLoading(true);
    fetch(`/api/docs?path=${encodeURIComponent(active)}`)
      .then((r) => r.json())
      .then((d: { content?: string }) => setContent(d.content ?? "*(could not load)*"))
      .catch(() => setContent("*(error loading doc)*"))
      .finally(() => setLoading(false));
  }, [active]);

  return (
    <div className="flex h-[calc(100vh-6.5rem)] gap-4">
      <aside className="w-72 shrink-0 overflow-auto rounded-lg border bg-card p-2">
        <p className="px-2 py-2 text-xs font-semibold text-muted-foreground">
          Docs ({docs.length})
        </p>
        <ul className="space-y-0.5">
          {docs.map((d) => (
            <li key={d}>
              <button
                onClick={() => setActive(d)}
                className={cn(
                  "flex w-full items-start gap-1.5 rounded-md px-2 py-1.5 text-left text-xs transition",
                  active === d ? "bg-secondary font-medium text-foreground" : "text-muted-foreground hover:bg-accent hover:text-foreground"
                )}
              >
                <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span className="break-all">{d}</span>
              </button>
            </li>
          ))}
        </ul>
      </aside>
      <main className="flex-1 overflow-auto rounded-lg border bg-card p-6">
        <p className="mb-4 font-mono text-xs text-muted-foreground">{active}</p>
        {loading ? (
          <div className="flex items-center gap-2 text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>
        ) : (
          <article className="prose prose-sm max-w-none">
            <Streamdown>{content}</Streamdown>
          </article>
        )}
      </main>
    </div>
  );
}
