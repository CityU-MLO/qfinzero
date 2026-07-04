"use client";

import { useEffect, useState } from "react";
import { Loader2, Save, RotateCcw, Check } from "lucide-react";

type Cfg = Record<string, string | number | boolean>;
type Fields = Record<string, { default: string | number | boolean; help: string }>;

const SELECTS: Record<string, string[]> = {
  default_market: ["us", "cn", "hk"],
  default_frequency: ["1d", "1m"],
  price_rule: ["close", "open"],
};

const GROUPS: { title: string; keys: string[] }[] = [
  { title: "Account defaults", keys: ["initial_cash", "default_market", "default_frequency", "buying_power_multiplier"] },
  { title: "Execution & pricing", keys: ["auto_price_from_upq", "price_rule", "slippage_bps"] },
  { title: "Fees", keys: ["fee_per_share", "option_fee_per_contract"] },
];

const LABEL: Record<string, string> = {
  initial_cash: "Initial cash", default_market: "Default market", default_frequency: "Default frequency",
  buying_power_multiplier: "Leverage (buying power ×)", auto_price_from_upq: "Fill at real UPQ price",
  price_rule: "Fill price rule", slippage_bps: "Slippage (bps)",
  fee_per_share: "Commission / share", option_fee_per_contract: "Commission / option contract",
};

export function PmbSettingsPanel() {
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const [fields, setFields] = useState<Fields>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [msg, setMsg] = useState("");

  async function load() {
    setMsg("");
    try {
      const res = await fetch("/api/pmb/v1/config");
      const d = await res.json();
      if (!res.ok) throw new Error(d.error ?? `HTTP ${res.status}`);
      setCfg(d.config); setFields(d.fields ?? {});
    } catch (e) { setMsg(String(e)); }
  }
  useEffect(() => { load(); }, []);

  function set(k: string, v: string | number | boolean) { setSaved(false); setCfg((c) => (c ? { ...c, [k]: v } : c)); }

  async function save() {
    if (!cfg) return;
    setSaving(true); setMsg("");
    try {
      const res = await fetch("/api/pmb/v1/config", {
        method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(cfg),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.error ?? `HTTP ${res.status}`);
      setCfg(d.config); setSaved(true); setTimeout(() => setSaved(false), 2000);
    } catch (e) { setMsg(String(e)); } finally { setSaving(false); }
  }

  function resetDefaults() {
    setCfg(Object.fromEntries(Object.entries(fields).map(([k, f]) => [k, f.default])) as Cfg);
    setSaved(false);
  }

  if (!cfg) return <div className="rounded-2xl border bg-white/80 p-4 text-sm text-muted-foreground">{msg || "Loading broker settings…"}</div>;

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div>
        <h3 className="text-sm font-semibold">Broker settings</h3>
        <p className="text-xs text-muted-foreground">Global defaults for the paper broker — applied to new accounts, fills, and pricing. Persisted server-side.</p>
      </div>

      {GROUPS.map((g) => (
        <div key={g.title} className="rounded-2xl border bg-white/80 p-4 shadow-sm">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{g.title}</div>
          <div className="grid gap-3 sm:grid-cols-2">
            {g.keys.filter((k) => k in cfg).map((k) => {
              const v = cfg[k];
              const help = fields[k]?.help;
              return (
                <label key={k} className="flex flex-col gap-1">
                  <span className="text-xs font-medium">{LABEL[k] ?? k}</span>
                  {typeof v === "boolean" ? (
                    <button type="button" onClick={() => set(k, !v)}
                      className={`flex h-8 w-full items-center rounded-lg border px-2 text-xs ${v ? "border-emerald-300 bg-emerald-50 text-emerald-700" : "bg-white text-muted-foreground"}`}>
                      <span className={`mr-2 h-3.5 w-3.5 rounded-full ${v ? "bg-emerald-500" : "bg-slate-300"}`} />
                      {v ? "On — real market fills" : "Off — agent supplies price"}
                    </button>
                  ) : SELECTS[k] ? (
                    <select value={String(v)} onChange={(e) => set(k, e.target.value)}
                      className="h-8 rounded-lg border bg-white px-2 text-sm">
                      {SELECTS[k].map((o) => <option key={o} value={o}>{o}</option>)}
                    </select>
                  ) : (
                    <input type="number" value={Number(v)} step="any"
                      onChange={(e) => set(k, e.target.value === "" ? 0 : Number(e.target.value))}
                      className="h-8 rounded-lg border px-2.5 text-sm" />
                  )}
                  {help && <span className="text-[11px] text-muted-foreground">{help}</span>}
                </label>
              );
            })}
          </div>
        </div>
      ))}

      <div className="flex items-center gap-3">
        <button onClick={save} disabled={saving}
          className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50">
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : saved ? <Check className="h-4 w-4" /> : <Save className="h-4 w-4" />}
          {saved ? "Saved" : "Save settings"}
        </button>
        <button onClick={resetDefaults} className="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm hover:bg-accent">
          <RotateCcw className="h-4 w-4" /> Reset to defaults
        </button>
        {msg && <span className="text-xs text-red-600">{msg}</span>}
      </div>
    </div>
  );
}
