"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Check, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fromZonedTime, toZonedTime } from "date-fns-tz";
import { useT } from "@/components/locale-provider";
import {
  API_META, CHANGE_EVENT, STORAGE_KEY as GROUPS_KEY, loadSettings, resolve, type ApiType, type ModelSettings,
} from "@/lib/model-groups";

export interface PlaygroundConfig {
  api: ApiType;
  model: string;
  baseUrl: string;
  apiKey: string;
  asOfDate: string;
  proxy?: string; // optional LLM egress proxy; empty = use server default (LLM_PROXY)
  contextTokens?: number; // context window the conversation is fitted into
  autoCompact?: boolean;  // summarise older turns when the context is nearly full
}

export const CONTEXT_CHOICES = [32_000, 64_000, 128_000, 200_000, 400_000, 1_000_000];

const STORAGE_KEY = "playground_config";
export const ET_ZONE = "America/New_York";

export const DEFAULT_CONFIG: PlaygroundConfig = {
  api: "openai",
  model: "",
  baseUrl: "",
  apiKey: "",
  // Default: today at 09:00 ET stored as UTC ISO string
  asOfDate: getDefaultAsOfDate(),
  proxy: "",
  contextTokens: 128_000,
  autoCompact: true,
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

/** Keep the chat config on the model groups of the Settings page: the model
 * picked there is the default, and credentials always come from its group.
 * Used by the layout, so it applies while the settings drawer is closed. */
export function useModelGroupSync(config: PlaygroundConfig, onChange: (c: PlaygroundConfig) => void) {
  const [groups, setGroups] = useState<ModelSettings | null>(null);
  useEffect(() => {
    const reload = () => setGroups(loadSettings());
    reload();
    const onStorage = (e: StorageEvent) => e.key === GROUPS_KEY && reload();
    window.addEventListener("storage", onStorage);
    window.addEventListener(CHANGE_EVENT, reload);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(CHANGE_EVENT, reload);
    };
  }, []);
  useEffect(() => {
    if (!groups) return;
    const current = groups.groups.find((g) => g.baseUrl === config.baseUrl && g.api === config.api &&
      g.models.some((m) => m.id === config.model));
    const r = current ? resolve(groups, current.id, config.model) : resolve(groups);
    if (r && (r.model !== config.model || r.baseUrl !== config.baseUrl || r.apiKey !== config.apiKey ||
              r.api !== config.api || (groups.proxy ?? "") !== (config.proxy ?? ""))) {
      onChange({ ...config, api: r.api, model: r.model, baseUrl: r.baseUrl, apiKey: r.apiKey, proxy: groups.proxy });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groups, config.model, config.baseUrl]);
}

interface ConfigPanelProps {
  config: PlaygroundConfig;
  onChange: (config: PlaygroundConfig) => void;
  disabled?: boolean;
}

export function ConfigPanel({ config, onChange, disabled }: ConfigPanelProps) {
  const t = useT();
  const [saved, setSaved] = useState(false);
  const [groups, setGroups] = useState<ModelSettings | null>(null);

  useEffect(() => {
    const reload = () => setGroups(loadSettings());
    reload();
    // edits on the Settings page: other tabs fire "storage", this tab our own event
    const onStorage = (e: StorageEvent) => e.key === GROUPS_KEY && reload();
    window.addEventListener("storage", onStorage);
    window.addEventListener(CHANGE_EVENT, reload);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(CHANGE_EVENT, reload);
    };
  }, []);

  const currentValue = useMemo(() => {
    const g = groups?.groups.find((x) => x.baseUrl === config.baseUrl && x.api === config.api && x.models.some((m) => m.id === config.model));
    return g ? `${g.id}::${config.model}` : "";
  }, [groups, config.api, config.baseUrl, config.model]);

  function selectModel(value: string) {
    if (!groups) return;
    setSaved(false);
    const i = value.indexOf("::");
    const r = resolve(groups, value.slice(0, i), value.slice(i + 2));
    if (r) onChange({ ...config, api: r.api, model: r.model, baseUrl: r.baseUrl, apiKey: r.apiKey, proxy: groups.proxy });
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
    <aside className="flex w-72 shrink-0 flex-col gap-5 overflow-y-auto border-l bg-card p-5">
      <div>
        <h2 className="text-xs font-semibold text-muted-foreground mb-3">
          {t("LLM Config", "LLM 配置")}
        </h2>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <Label htmlFor="model" className="text-xs">{t("Model", "模型")}</Label>
            <select
              id="model"
              value={currentValue}
              onChange={(e) => selectModel(e.target.value)}
              disabled={disabled}
              className="h-8 rounded-md border bg-card px-2 text-sm disabled:opacity-50"
            >
              {currentValue === "" && (
                <option value="">{config.model || t("Select a model…", "选择模型…")}</option>
              )}
              {(groups?.groups ?? []).filter((g) => g.models.length).map((g) => (
                <optgroup key={g.id} label={`${g.name} · ${API_META[g.api].label}`}>
                  {g.models.map((m) => (
                    <option key={`${g.id}::${m.id}`} value={`${g.id}::${m.id}`}>{m.id}</option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>

          {/* Base URL / API key / proxy are configured in Settings and resolved here */}
          <div className="flex items-center justify-between text-[11px]">
            <span className={hasKey ? "text-success" : "text-warning"}>
              {hasKey ? t("● key set", "● 已设置密钥") : t("● no key", "● 未设置密钥")}
            </span>
            <Link href="/settings" className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground">
              {t("Manage in Settings", "在设置中管理")} <ExternalLink className="h-3 w-3" />
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
                  <Check className="h-3 w-3 text-success" />
                  {t("Saved", "已保存")}
                </>
              ) : (
                t("Save", "保存")
              )}
            </Button>
          </div>
        </div>
      </div>

      <div>
        <h2 className="text-xs font-semibold text-muted-foreground mb-3">
          {t("Context", "上下文")}
        </h2>
        <div className="flex flex-col gap-1">
          <Label htmlFor="asOfDate" className="text-xs">
            {t("As of Date", "截止时间")} <span className="text-muted-foreground font-normal">{t("(ET)", "（美东时间）")}</span>
          </Label>
          <Input
            id="asOfDate"
            type="datetime-local"
            value={utcToDatetimeLocal(config.asOfDate)}
            onChange={(e) => setAsOf(e.target.value)}
            disabled={disabled}
            className="text-sm h-8"
          />
          <span className="text-[11px] text-muted-foreground">
            {t("Tools see no data after this time.", "工具看不到这个时间之后的数据。")}
          </span>
        </div>
        <div className="mt-3 flex flex-col gap-1">
          <Label htmlFor="ctx" className="text-xs">{t("Context window", "上下文窗口")}</Label>
          <select id="ctx" value={config.contextTokens ?? 128_000} disabled={disabled}
            onChange={(e) => { setSaved(false); onChange({ ...config, contextTokens: Number(e.target.value) }); }}
            className="h-8 rounded-md border bg-card px-2 text-sm disabled:opacity-50">
            {CONTEXT_CHOICES.map((n) => <option key={n} value={n}>{n >= 1_000_000 ? `${n / 1_000_000}M` : `${n / 1000}k`} tokens</option>)}
          </select>
          <span className="text-[11px] text-muted-foreground">
            {t("Set it to your model's window. Old tool results are shortened first.",
              "设为模型的上下文长度。较早的工具结果会先被截短。")}
          </span>
        </div>
        <label className="mt-3 flex items-start gap-2 text-xs">
          <input type="checkbox" className="mt-0.5" checked={config.autoCompact ?? true} disabled={disabled}
            onChange={(e) => { setSaved(false); onChange({ ...config, autoCompact: e.target.checked }); }} />
          <span>
            {t("Auto-compact", "自动压缩")}
            <span className="block text-[11px] text-muted-foreground">
              {t("At 80% of the window, summarise older turns (they stay in the history and exports).",
                "达到窗口的 80% 时总结较早的对话（原文仍保留在历史和导出中）。")}
            </span>
          </span>
        </label>
      </div>
    </aside>
  );
}
