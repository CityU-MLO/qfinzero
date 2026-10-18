"use client";

import { useCallback, useEffect, useState } from "react";

import { chatApi, type ThreadSummary } from "@/lib/chat-api";

import { ChatPanel } from "./chat-panel";
import { ChatSidebar } from "./chat-sidebar";
import { ConfigPanel, DEFAULT_CONFIG, PlaygroundConfig, loadConfig, saveConfig, useModelGroupSync } from "./config-panel";

const SETTINGS_OPEN = "playground_settings_open";

function threadFromUrl(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("thread");
}

export function PlaygroundLayout() {
  const [config, setConfig] = useState<PlaygroundConfig>(DEFAULT_CONFIG);
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState<string | null>(null);
  const [settings, setSettings] = useState(false);
  const [sidebar, setSidebar] = useState(true);

  // Defer localStorage / URL reads to after hydration to avoid SSR/CSR mismatch
  useEffect(() => {
    setConfig(loadConfig());
    setActive(threadFromUrl());
    if (window.innerWidth < 900) setSidebar(false);
    try { setSettings(localStorage.getItem(SETTINGS_OPEN) === "1"); } catch { /* private mode */ }
  }, []);

  const refresh = useCallback(async () => {
    try {
      setThreads((await chatApi.list(query)).threads);
    } catch { /* service down: the panel shows the error on send */ } finally {
      setLoading(false);
    }
  }, [query]);

  useEffect(() => {
    const h = setTimeout(() => void refresh(), query ? 250 : 0);
    return () => clearTimeout(h);
  }, [refresh, query]);

  // keep running threads' spinners current
  useEffect(() => {
    if (!threads.some((t) => t.running)) return;
    const h = setInterval(() => void refresh(), 3000);
    return () => clearInterval(h);
  }, [threads, refresh]);

  const select = useCallback((id: string | null) => {
    setActive(id);
    const url = new URL(window.location.href);
    if (id) url.searchParams.set("thread", id); else url.searchParams.delete("thread");
    window.history.replaceState(null, "", url.toString());
  }, []);

  // a thread remembers its simulation time: continue it there
  useEffect(() => {
    const th = threads.find((t) => t.id === active);
    if (th?.as_of && th.as_of !== config.asOfDate) setConfig((c) => ({ ...c, asOfDate: th.as_of as string }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  const changeConfig = useCallback((c: PlaygroundConfig) => {
    setConfig(c);
    try { saveConfig(c); } catch { /* storage unavailable */ }
  }, []);
  useModelGroupSync(config, changeConfig);

  return (
    <div className="flex min-h-0 flex-1 overflow-hidden rounded-lg border bg-card">
      {sidebar && <ChatSidebar threads={threads} activeId={active} loading={loading} query={query} onQuery={setQuery}
        onSelect={select} onNew={() => select(null)}
        onDelete={async (id) => { await chatApi.remove(id); if (id === active) select(null); void refresh(); }}
        onRename={async (id, title) => { await chatApi.rename(id, title); void refresh(); }} />}
      <ChatPanel config={config} threadId={active} onThread={select} onThreadsChanged={refresh}
        onToggleSidebar={() => setSidebar((s) => !s)}
        onToggleSettings={() => setSettings((s) => {
          try { localStorage.setItem(SETTINGS_OPEN, s ? "0" : "1"); } catch { /* ignore */ }
          return !s;
        })} />
      {settings && <ConfigPanel config={config} onChange={changeConfig} />}
    </div>
  );
}
