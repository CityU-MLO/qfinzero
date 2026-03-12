"use client";

import { useState } from "react";
import { Check, Loader2, Wifi, WifiOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { fromZonedTime, toZonedTime } from "date-fns-tz";

export interface PlaygroundConfig {
  model: string;
  baseUrl: string;
  apiKey: string;
  asOfDate: string;
}

const STORAGE_KEY = "playground_config";
export const ET_ZONE = "America/New_York";

export const DEFAULT_CONFIG: PlaygroundConfig = {
  model: "gpt-4o-mini",
  baseUrl: "https://api.openai.com/v1",
  apiKey: "",
  // Default: today at 09:00 ET stored as UTC ISO string
  asOfDate: getDefaultAsOfDate(),
};

/** Returns today at 09:00 US/Eastern as a UTC ISO string "YYYY-MM-DDTHH:MM:SSZ" */
function getDefaultAsOfDate(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  // Build "YYYY-MM-DD 09:00" as an ET wall-clock string, then convert to UTC
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

type TestStatus = "idle" | "loading" | "ok" | "error";

interface ConfigPanelProps {
  config: PlaygroundConfig;
  onChange: (config: PlaygroundConfig) => void;
  disabled?: boolean;
}

export function ConfigPanel({ config, onChange, disabled }: ConfigPanelProps) {
  const [saved, setSaved] = useState(false);
  const [testStatus, setTestStatus] = useState<TestStatus>("idle");
  const [testError, setTestError] = useState<string>("");

  function set(key: keyof PlaygroundConfig, value: string) {
    // Reset indicators when config changes
    setSaved(false);
    setTestStatus("idle");
    // asOfDate is stored as UTC ISO; convert from datetime-local (ET) on input
    const stored = key === "asOfDate" ? datetimeLocalToUtc(value) : value;
    onChange({ ...config, [key]: stored });
  }

  function handleSave() {
    saveConfig(config);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  async function handleTest() {
    setTestStatus("loading");
    setTestError("");
    try {
      const res = await fetch("/api/playground/test-connection", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ base_url: config.baseUrl, api_key: config.apiKey }),
      });
      const data = (await res.json()) as { ok: boolean; error?: string };
      if (data.ok) {
        setTestStatus("ok");
        setTimeout(() => setTestStatus("idle"), 3000);
      } else {
        setTestStatus("error");
        setTestError(data.error ?? "Connection failed");
      }
    } catch (e) {
      setTestStatus("error");
      setTestError((e as Error).message);
    }
  }

  return (
    <aside className="flex flex-col gap-5 p-5 border-r min-w-[240px] max-w-[280px] bg-white/60 rounded-l-2xl">
      <div>
        <h2 className="text-xs font-bold uppercase tracking-widest text-muted-foreground mb-3">
          LLM Config
        </h2>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <Label htmlFor="model" className="text-xs">Model</Label>
            <Input
              id="model"
              value={config.model}
              onChange={(e) => set("model", e.target.value)}
              placeholder="gpt-4o-mini"
              disabled={disabled}
              className="text-sm h-8"
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="baseUrl" className="text-xs">Base URL</Label>
            <Input
              id="baseUrl"
              value={config.baseUrl}
              onChange={(e) => set("baseUrl", e.target.value)}
              placeholder="https://api.openai.com/v1"
              disabled={disabled}
              className="text-sm h-8"
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="apiKey" className="text-xs">API Key</Label>
            <Input
              id="apiKey"
              type="password"
              value={config.apiKey}
              onChange={(e) => set("apiKey", e.target.value)}
              placeholder="sk-..."
              disabled={disabled}
              className="text-sm h-8"
            />
          </div>

          {/* Save + Test buttons */}
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
            <Button
              size="sm"
              variant="outline"
              className={cn(
                "flex-1 h-8 text-xs gap-1.5",
                testStatus === "ok" && "border-green-500 text-green-600",
                testStatus === "error" && "border-red-400 text-red-600"
              )}
              onClick={() => void handleTest()}
              disabled={disabled || testStatus === "loading" || !config.baseUrl || !config.apiKey}
            >
              {testStatus === "loading" && <Loader2 className="h-3 w-3 animate-spin" />}
              {testStatus === "ok" && <Wifi className="h-3 w-3" />}
              {testStatus === "error" && <WifiOff className="h-3 w-3" />}
              {testStatus === "idle" && <Wifi className="h-3 w-3" />}
              {testStatus === "loading" ? "Testing..." : testStatus === "ok" ? "Connected" : testStatus === "error" ? "Failed" : "Test"}
            </Button>
          </div>

          {/* Test error message */}
          {testStatus === "error" && testError && (
            <p className="text-xs text-red-500 leading-snug break-all">{testError}</p>
          )}
        </div>
      </div>

      <div>
        <h2 className="text-xs font-bold uppercase tracking-widest text-muted-foreground mb-3">
          Context
        </h2>
        <div className="flex flex-col gap-1">
          <Label htmlFor="asOfDate" className="text-xs">As of Date <span className="text-muted-foreground font-normal">(ET)</span></Label>
          <Input
            id="asOfDate"
            type="datetime-local"
            value={utcToDatetimeLocal(config.asOfDate)}
            onChange={(e) => set("asOfDate", e.target.value)}
            disabled={disabled}
            className="text-sm h-8"
          />
        </div>
      </div>
    </aside>
  );
}
