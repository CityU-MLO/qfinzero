"use client";

import { useEffect, useState } from "react";
import { Check, Loader2, Plus, Trash2, Wifi, WifiOff } from "lucide-react";

type Provider = {
  id: string;
  label: string;
  baseUrl: string;
  apiKey: string;
  models: string[];
  builtin: boolean;
};

type ConsoleSettings = {
  providers: Provider[];
  activeProviderId: string;
  activeModel: string;
  proxy: string; // LLM egress proxy; blank = use the server default (LLM_PROXY)
};

const SETTINGS_KEY = "qfz_console_settings";
const PLAYGROUND_KEY = "playground_config"; // the Chat reads this

const DEFAULT_PROVIDERS: Provider[] = [
  { id: "openai", label: "OpenAI (GPT)", baseUrl: "https://api.openai.com/v1", apiKey: "", models: ["gpt-4o", "gpt-4o-mini", "o3-mini"], builtin: true },
  { id: "deepseek", label: "DeepSeek", baseUrl: "https://api.deepseek.com", apiKey: "", models: ["deepseek-chat", "deepseek-reasoner"], builtin: true },
  { id: "gemini", label: "Gemini", baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai", apiKey: "", models: ["gemini-2.0-flash", "gemini-1.5-pro"], builtin: true },
  { id: "claude", label: "Claude (Anthropic)", baseUrl: "https://api.anthropic.com/v1", apiKey: "", models: ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"], builtin: true },
];

function defaultSettings(): ConsoleSettings {
  return { providers: DEFAULT_PROVIDERS, activeProviderId: "openai", activeModel: "gpt-4o-mini", proxy: "" };
}

function loadSettings(): ConsoleSettings {
  if (typeof window === "undefined") return defaultSettings();
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return defaultSettings();
    const parsed = JSON.parse(raw) as ConsoleSettings;
    // merge built-ins so new defaults appear, keep user edits/custom
    const byId = new Map(parsed.providers.map((p) => [p.id, p]));
    const merged = [...DEFAULT_PROVIDERS.map((d) => byId.get(d.id) ?? d), ...parsed.providers.filter((p) => !p.builtin)];
    return { ...parsed, providers: merged };
  } catch {
    return defaultSettings();
  }
}

const inputCls = "w-full rounded-lg border bg-white px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200";

export default function SettingsPage() {
  const [settings, setSettings] = useState<ConsoleSettings>(defaultSettings());
  const [saved, setSaved] = useState(false);
  const [test, setTest] = useState<Record<string, "idle" | "loading" | "ok" | "error">>({});
  const [testErr, setTestErr] = useState<Record<string, string>>({});
  const [envLoaded, setEnvLoaded] = useState<Record<string, boolean>>({});
  const [proxyLoaded, setProxyLoaded] = useState(false);

  useEffect(() => {
    const s = loadSettings();
    // pre-fill provider keys from server-side env (.env.local), only when empty
    fetch("/api/providers/env-keys")
      .then((r) => r.json())
      .then((d: { keys?: Record<string, string>; loaded?: Record<string, boolean>; proxyLoaded?: boolean }) => {
        const providers = s.providers.map((p) =>
          !p.apiKey && d.keys?.[p.id] ? { ...p, apiKey: d.keys[p.id] } : p
        );
        setSettings({ ...s, providers });
        setEnvLoaded(d.loaded ?? {});
        setProxyLoaded(Boolean(d.proxyLoaded));
      })
      .catch(() => setSettings(s));
  }, []);

  const active = settings.providers.find((p) => p.id === settings.activeProviderId) ?? settings.providers[0];

  function update(next: Partial<ConsoleSettings>) {
    setSaved(false);
    setSettings((s) => ({ ...s, ...next }));
  }

  function updateProvider(id: string, patch: Partial<Provider>) {
    setSaved(false);
    setSettings((s) => ({ ...s, providers: s.providers.map((p) => (p.id === id ? { ...p, ...patch } : p)) }));
  }

  function addCustom() {
    const id = `custom-${Date.now()}`;
    update({
      providers: [
        ...settings.providers,
        { id, label: "Custom / local vLLM", baseUrl: "http://localhost:8000/v1", apiKey: "", models: ["local-model"], builtin: false },
      ],
    });
  }

  function removeProvider(id: string) {
    update({ providers: settings.providers.filter((p) => p.id !== id) });
  }

  function save() {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    // mirror the active provider into the Chat's config so it uses this selection
    let pg: Record<string, unknown> = {};
    try {
      pg = JSON.parse(localStorage.getItem(PLAYGROUND_KEY) ?? "{}");
    } catch {
      pg = {};
    }
    localStorage.setItem(
      PLAYGROUND_KEY,
      JSON.stringify({ ...pg, model: settings.activeModel, baseUrl: active?.baseUrl, apiKey: active?.apiKey, proxy: settings.proxy })
    );
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  async function testConnection(p: Provider) {
    setTest((t) => ({ ...t, [p.id]: "loading" }));
    setTestErr((e) => ({ ...e, [p.id]: "" }));
    try {
      const res = await fetch("/api/playground/test-connection", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ base_url: p.baseUrl, api_key: p.apiKey, proxy: settings.proxy || undefined }),
      });
      const data = (await res.json()) as { ok: boolean; error?: string };
      if (data.ok) setTest((t) => ({ ...t, [p.id]: "ok" }));
      else {
        setTest((t) => ({ ...t, [p.id]: "error" }));
        setTestErr((e) => ({ ...e, [p.id]: data.error ?? "Connection failed" }));
      }
    } catch (err) {
      setTest((t) => ({ ...t, [p.id]: "error" }));
      setTestErr((e) => ({ ...e, [p.id]: (err as Error).message }));
    }
  }

  return (
    <div className="space-y-6">
      <section>
        <h2 className="text-xl font-semibold">Settings — LLM Providers</h2>
        <p className="text-sm text-muted-foreground">
          Configure providers and pick the active model used by Chat. Keys are stored only in this browser.
        </p>
      </section>

      {/* Active selector */}
      <div className="rounded-2xl border bg-white/80 p-4 shadow-sm">
        <h3 className="mb-3 text-xs font-bold uppercase tracking-widest text-muted-foreground">Active model</h3>
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Provider</span>
            <select
              className={inputCls}
              value={settings.activeProviderId}
              onChange={(e) => {
                const p = settings.providers.find((x) => x.id === e.target.value);
                update({ activeProviderId: e.target.value, activeModel: p?.models[0] ?? settings.activeModel });
              }}
            >
              {settings.providers.map((p) => (
                <option key={p.id} value={p.id}>{p.label}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Model</span>
            <select className={inputCls} value={settings.activeModel} onChange={(e) => update({ activeModel: e.target.value })}>
              {(active?.models ?? []).map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </label>
          <button
            onClick={save}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow hover:opacity-90"
          >
            {saved ? <><Check className="h-4 w-4" /> Saved</> : "Save"}
          </button>
        </div>
        <div className="mt-4 border-t pt-4">
          <label className="flex flex-col gap-1">
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              LLM egress proxy <span className="font-normal">(optional)</span>
              {proxyLoaded && (
                <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium text-emerald-600">server proxy active</span>
              )}
            </span>
            <input
              className={inputCls}
              placeholder="http://user:pass@host:3128 — blank uses the server default"
              value={settings.proxy}
              onChange={(e) => update({ proxy: e.target.value })}
            />
            <span className="text-[11px] text-muted-foreground">
              Routes provider API calls through this proxy (Chat + Test connection). Local services bypass it. Leave blank to use the server&apos;s LLM_PROXY.
            </span>
          </label>
        </div>
      </div>

      {/* Providers */}
      <div className="grid gap-4 md:grid-cols-2">
        {settings.providers.map((p) => (
          <div key={p.id} className="rounded-2xl border bg-white/80 p-4 shadow-sm">
            <div className="mb-3 flex items-center justify-between">
              <input
                className="rounded-md bg-transparent text-sm font-semibold outline-none"
                value={p.label}
                onChange={(e) => updateProvider(p.id, { label: e.target.value })}
              />
              <div className="flex items-center gap-2">
                {p.builtin ? (
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500">built-in</span>
                ) : (
                  <button onClick={() => removeProvider(p.id)} className="text-slate-400 hover:text-red-500" title="Remove">
                    <Trash2 className="h-4 w-4" />
                  </button>
                )}
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Base URL</span>
                <input className={inputCls} value={p.baseUrl} onChange={(e) => updateProvider(p.id, { baseUrl: e.target.value })} />
              </label>
              <label className="flex flex-col gap-1">
                <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  API key
                  {envLoaded[p.id] && (
                    <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium text-emerald-600">loaded from env</span>
                  )}
                </span>
                <input type="password" className={inputCls} placeholder="sk-…  (leave blank for local)" value={p.apiKey} onChange={(e) => updateProvider(p.id, { apiKey: e.target.value })} />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Models (comma-separated)</span>
                <input
                  className={inputCls}
                  value={p.models.join(", ")}
                  onChange={(e) => updateProvider(p.id, { models: e.target.value.split(",").map((m) => m.trim()).filter(Boolean) })}
                />
              </label>
              <div className="flex items-center gap-2 pt-1">
                <button
                  onClick={() => testConnection(p)}
                  disabled={test[p.id] === "loading" || !p.baseUrl}
                  className="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs hover:bg-accent disabled:opacity-50"
                >
                  {test[p.id] === "loading" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  {test[p.id] === "ok" && <Wifi className="h-3.5 w-3.5 text-emerald-500" />}
                  {test[p.id] === "error" && <WifiOff className="h-3.5 w-3.5 text-red-500" />}
                  {test[p.id] === "loading" ? "Testing…" : test[p.id] === "ok" ? "Connected" : test[p.id] === "error" ? "Failed" : "Test connection"}
                </button>
                {test[p.id] === "error" && testErr[p.id] && (
                  <span className="text-xs text-red-500 truncate">{testErr[p.id]}</span>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      <button onClick={addCustom} className="flex items-center gap-1.5 rounded-lg border px-4 py-2 text-sm hover:bg-accent">
        <Plus className="h-4 w-4" /> Add custom provider (local vLLM, …)
      </button>
    </div>
  );
}
