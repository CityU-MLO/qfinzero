"use client";

import { useEffect, useState } from "react";
import { ExternalLink, MonitorPlay, Settings2 } from "lucide-react";

import { useLegacySkin } from "@/components/app-providers";
import { PmbSettingsPanel } from "@/components/pmb/settings-panel";
import { cn } from "@/lib/utils";

type Tab = "terminal" | "settings";

export default function PmbPage() {
  const legacy = useLegacySkin();
  const [tab, setTab] = useState<Tab>("terminal");
  const [src, setSrc] = useState<string>("");

  useEffect(() => {
    const host = window.location.hostname || "127.0.0.1";
    const port = process.env.NEXT_PUBLIC_PMB_PORT ?? "19380";
    const skin = legacy ? "?theme=win98" : "";
    setSrc(`${window.location.protocol}//${host}:${port}/ui/${skin}`);
  }, [legacy]);

  return (
    <div className="flex flex-col h-[calc(100vh-7rem)] gap-3">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">PMB — Paper Money Broker</h2>
          <p className="text-sm text-muted-foreground">
            A broker for LLM agents: real UPQ-priced fills, day-by-day history — and one place to tune it.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-lg border bg-white/70 p-0.5 text-sm">
            {([["terminal", "Terminal", MonitorPlay], ["settings", "Settings", Settings2]] as const).map(
              ([id, label, Icon]) => (
                <button key={id} onClick={() => setTab(id)}
                  className={cn("flex items-center gap-1.5 rounded-md px-3 py-1.5 transition",
                    tab === id ? "bg-indigo-600 text-white" : "text-muted-foreground hover:text-foreground")}>
                  <Icon className="h-3.5 w-3.5" /> {label}
                </button>
              ),
            )}
          </div>
          {tab === "terminal" && src && (
            <a href={src} target="_blank" rel="noopener noreferrer"
              className="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm hover:bg-accent">
              Open in new tab <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}
        </div>
      </div>

      {tab === "terminal" ? (
        <div className="flex-1 min-h-0 rounded-2xl border bg-white shadow-sm overflow-hidden">
          {src ? (
            <iframe src={src} title="PMB Broker Terminal" className="h-full w-full border-0" />
          ) : (
            <div className="flex h-full items-center justify-center text-muted-foreground">Loading…</div>
          )}
        </div>
      ) : (
        <div className="flex-1 min-h-0 overflow-auto">
          <PmbSettingsPanel />
        </div>
      )}
    </div>
  );
}
