"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Check, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fromZonedTime, toZonedTime } from "date-fns-tz";

export interface PlaygroundConfig {
  model: string;
  baseUrl: string;
  apiKey: string;
  asOfDate: string;
  proxy?: string; // optional LLM egress proxy; empty = use server default (LLM_PROXY)
}

const STORAGE_KEY = "playground_config";
const SETTINGS_KEY = "qfz_console_settings"; // written by the Settings page
export const ET_ZONE = "America/New_York";

// ── Provider registry (mirrors the Settings page; base_url/api_key resolved here) ──
type Provider = { id: string; label: string; baseUrl: string; apiKey: string; models: string[] };
type ConsoleSettings = { providers: Provider[]; activeProviderId: string; activeModel: string; proxy: string };

const DEFAULT_PROVIDERS: Provider[] = [
  { id: "openai", label: "OpenAI (GPT)", baseUrl: "https://api.openai.com/v1", apiKey: "", models: ["gpt-4o", "gpt-4o-mini", "o3-mini"] },
  { id: "deepseek", label: "DeepSeek", baseUrl: "https://api.deepseek.com", apiKey: "", models: ["deepseek-chat", "deepseek-reasoner"] },
  { id: "gemini", label: "Gemini", baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai", apiKey: "", models: ["gemini-2.0-flash", "gemini-1.5-pro"] },
  { id: "claude", label: "Claude (Anthropic)", baseUrl: "https://api.anthropic.com/v1", apiKey: "", models: ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"] },
];

function loadConsoleSettings(): ConsoleSettings {
  const fallback: ConsoleSettings = { providers: DEFAULT_PROVIDERS, activeProviderId: "openai", activeModel: "gpt-4o-mini", proxy: "" };
  if (typeof window === "undefined") return fallback;
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<ConsoleSettings>;
    if (!parsed.providers?.length) return fallback;
    return { ...fallback, ...parsed, providers: parsed.providers };
  } catch {
    return fallback;
  }
}

export const DEFAULT_CONFIG: PlaygroundConfig = {
  model: "gpt-4o-mini",
  baseUrl: "https://api.openai.com/v1",
  apiKey: "",
  // Default: today at 09:00 ET stored as UTC ISO string
  asOfDate: getDefaultAsOfDate(),
  proxy: "",
};

/** Returns today at 09:00 US/Eastern as a UTC ISO string "YYYY-MM-DDTHH:MM:SSZ" */
function getDefaultAsOfDate(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  const dateStr = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  const etNine = fromZonedTime(`${dateStr}T09:00:00`, ET_ZONE);
  return etNine.toISOString();
}

/** Convert a UTC ISO string to the value format used by datetime-local input ("YYYY-MM-DDTHH:MM") */
export function utcToDatetimeLocal(utcIso: string): string {
  const d = new Date(utcIso);
  const et = toZonedTime(d, ET_ZONE);
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${et.getFullYear()}-${pad(et.getMonth() + 1)}-${pad(et.getDate())}` +
    `T${pad(et.getHours())}:${pad(et.getMinutes())}`
  );
}

/** Convert a datetime-local string ("YYYY-MM-DDTHH:MM") interpreted as ET back to UTC ISO string */
export function datetimeLocalToUtc(local: string): string {
  return fromZonedTime(local, ET_ZONE).toISOString();
}

export function loadConfig(): PlaygroundConfig {
  if (typeof window === "undefined") return DEFAULT_CONFIG;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? { ...DEFAULT_CONFIG, ...JSON.parse(raw) } : DEFAULT_CONFIG;
  } catch {
    return DEFAULT_CONFIG;
  }
}

export function saveConfig(config: PlaygroundConfig) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
}

interface ConfigPanelProps {
  config: PlaygroundConfig;
  onChange: (config: PlaygroundConfig) => void;
  disabled?: boolean;
}

export function ConfigPanel({ config, onChange, disabled }: ConfigPanelProps) {
  const [saved, setSaved] = useState(false);
  const [settings, setSettings] = useState<ConsoleSettings | null>(null);

  useEffect(() => {
    setSettings(loadConsoleSettings());
    // pick up edits made on the Settings page in another tab
    const onStorage = (e: StorageEvent) => {
      if (e.key === SETTINGS_KEY) setSettings(loadConsoleSettings());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const providers = settings?.providers ?? DEFAULT_PROVIDERS;

  // Which "<providerId>::<model>" option is currently selected.
  const currentValue = useMemo(() => {
    for (const p of providers)
      for (const m of p.models)
        if (m === config.model && p.baseUrl === config.baseUrl) return `${p.id}::${m}`;
    for (const p of providers)
      for (const m of p.models) if (m === config.model) return `${p.id}::${m}`;
    return "";
  }, [providers, config.model, config.baseUrl]);

  // Once settings load, sync the current model's credentials from the provider
  // registry (so Chat uses the keys configured in Settings, not stale ones).
  useEffect(() => {
    if (!settings) return;
    const [pid] = (currentValue || "").split("::");
    const p = providers.find((x) => x.id === pid);
    if (p && (p.baseUrl !== config.baseUrl || p.apiKey !== config.apiKey || (settings.proxy ?? "") !== (config.proxy ?? ""))) {
      onChange({ ...config, baseUrl: p.baseUrl, apiKey: p.apiKey, proxy: settings.proxy ?? config.proxy });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings]);

  function selectModel(value: string) {
    setSaved(false);
    const [pid, m] = value.split("::");
    const p = providers.find((x) => x.id === pid);
    if (!p) return;
    onChange({ ...config, model: m, baseUrl: p.baseUrl, apiKey: p.apiKey, proxy: settings?.proxy ?? config.proxy });
  }

  function setAsOf(value: string) {
    setSaved(false);
    onChange({ ...config, asOfDate: datetimeLocalToUtc(value) });
  }

  function handleSave() {
    saveConfig(config);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  const hasKey = Boolean(config.apiKey);

  return (
    <aside className="flex flex-col gap-5 p-5 border-r min-w-[240px] max-w-[280px] bg-white/60 rounded-l-2xl">
      <div>
        <h2 className="text-xs font-bold uppercase tracking-widest text-muted-foreground mb-3">
          LLM Config
        </h2>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <Label htmlFor="model" className="text-xs">Model</Label>
            <select
              id="model"
              value={currentValue}
              onChange={(e) => selectModel(e.target.value)}
              disabled={disabled}
              className="h-8 rounded-md border bg-white px-2 text-sm disabled:opacity-50"
            >
              {currentValue === "" && (
                <option value="">{config.model || "Select a model…"}</option>
              )}
              {providers.map((p) => (
                <optgroup key={p.id} label={p.label}>
                  {p.models.map((m) => (
                    <option key={`${p.id}::${m}`} value={`${p.id}::${m}`}>{m}</option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>

          {/* Base URL / API key / proxy are configured in Settings and resolved here */}
          <div className="flex items-center justify-between text-[11px]">
            <span className={hasKey ? "text-emerald-600" : "text-amber-600"}>
              {hasKey ? "● key set" : "● no key"}
            </span>
            <Link href="/settings" className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground">
              Manage in Settings <ExternalLink className="h-3 w-3" />
            </Link>
          </div>

          <div className="flex gap-2 pt-1">
            <Button
              size="sm"
              variant="outline"
              className="flex-1 h-8 text-xs gap-1.5"
              onClick={handleSave}
              disabled={disabled}
            >
              {saved ? (
                <>
                  <Check className="h-3 w-3 text-green-500" />
                  Saved
                </>
              ) : (
                "Save"
              )}
            </Button>
          </div>
        </div>
      </div>

      <div>
        <h2 className="text-xs font-bold uppercase tracking-widest text-muted-foreground mb-3">
          Context
        </h2>
        <div className="flex flex-col gap-1">
          <Label htmlFor="asOfDate" className="text-xs">
            As of Date <span className="text-muted-foreground font-normal">(ET)</span>
          </Label>
          <Input
            id="asOfDate"
            type="datetime-local"
            value={utcToDatetimeLocal(config.asOfDate)}
            onChange={(e) => setAsOf(e.target.value)}
            disabled={disabled}
            className="text-sm h-8"
          />
        </div>
      </div>
    </aside>
  );
}
