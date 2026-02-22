"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export interface PlaygroundConfig {
  model: string;
  baseUrl: string;
  apiKey: string;
  asOfDate: string;
}

const STORAGE_KEY = "playground_config";

const DEFAULT_CONFIG: PlaygroundConfig = {
  model: "gpt-4o-mini",
  baseUrl: "https://api.openai.com/v1",
  apiKey: "",
  asOfDate: new Date().toISOString().slice(0, 10),
};

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
  function set(key: keyof PlaygroundConfig, value: string) {
    const next = { ...config, [key]: value };
    onChange(next);
    saveConfig(next);
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
        </div>
      </div>

      <div>
        <h2 className="text-xs font-bold uppercase tracking-widest text-muted-foreground mb-3">
          Context
        </h2>
        <div className="flex flex-col gap-1">
          <Label htmlFor="asOfDate" className="text-xs">As of Date</Label>
          <Input
            id="asOfDate"
            type="date"
            value={config.asOfDate}
            onChange={(e) => set("asOfDate", e.target.value)}
            disabled={disabled}
            className="text-sm h-8"
          />
        </div>
      </div>
    </aside>
  );
}
