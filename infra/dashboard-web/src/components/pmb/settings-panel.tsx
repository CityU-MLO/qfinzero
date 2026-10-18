"use client";

import { useEffect, useState } from "react";
import { Loader2, Save, RotateCcw, Check } from "lucide-react";

import { useT } from "@/components/locale-provider";

type Cfg = Record<string, string | number | boolean>;
type Fields = Record<string, { default: string | number | boolean; help: string }>;

const SELECTS: Record<string, string[]> = {
  default_market: ["us", "cn", "hk"],
  default_frequency: ["1d", "1m"],
  price_rule: ["close", "open"],
};

// Visible text for select options; the option value is what is saved.
const OPTION_LABEL: Record<string, readonly [string, string]> = {
  us: ["us", "美股"], cn: ["cn", "A股"], hk: ["hk", "港股"],
  "1d": ["1d", "日线"], "1m": ["1m", "1 分钟"],
  close: ["close", "收盘价"], open: ["open", "开盘价"],
};

const GROUPS: { title: readonly [string, string]; keys: string[] }[] = [
  { title: ["Account defaults", "账户默认值"], keys: ["initial_cash", "default_market", "default_frequency", "buying_power_multiplier"] },
  { title: ["Execution & pricing", "执行与定价"], keys: ["auto_price_from_upq", "price_rule", "slippage_bps"] },
  { title: ["Fees", "费用"], keys: ["fee_per_share", "option_fee_per_contract"] },
];

const LABEL: Record<string, readonly [string, string]> = {
  initial_cash: ["Initial cash", "初始资金"], default_market: ["Default market", "默认市场"],
  default_frequency: ["Default frequency", "默认频率"],
  buying_power_multiplier: ["Leverage (buying power ×)", "杠杆（购买力倍数）"],
  auto_price_from_upq: ["Fill at real UPQ price", "按 UPQ 真实价格成交"],
  price_rule: ["Fill price rule", "成交价规则"], slippage_bps: ["Slippage (bps)", "滑点（bps）"],
  fee_per_share: ["Commission / share", "佣金 / 股"],
  option_fee_per_contract: ["Commission / option contract", "佣金 / 期权合约（张）"],
};

export function PmbSettingsPanel() {
  const t = useT();
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

  if (!cfg) return <div className="rounded-lg border bg-card p-4 text-sm text-muted-foreground">{msg || t("Loading broker settings…", "正在加载交易设置…")}</div>;

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div>
        <h3 className="text-sm font-semibold">{t("Broker settings", "交易设置")}</h3>
        <p className="text-xs text-muted-foreground">
          {t(
            "Global defaults for the paper broker — applied to new accounts, fills, and pricing. Persisted server-side.",
            "模拟券商的全局默认设置，作用于新账户、成交和定价，保存在服务端。",
          )}
        </p>
      </div>

      {GROUPS.map((g) => (
        <div key={g.title[0]} className="rounded-lg border bg-card p-4">
          <div className="mb-2 text-xs font-semibold text-muted-foreground">{t(g.title[0], g.title[1])}</div>
          <div className="grid gap-3 sm:grid-cols-2">
            {g.keys.filter((k) => k in cfg).map((k) => {
              const v = cfg[k];
              const help = fields[k]?.help;
              return (
                <label key={k} className="flex flex-col gap-1">
                  <span className="text-xs font-medium">{LABEL[k] ? t(LABEL[k][0], LABEL[k][1]) : k}</span>
                  {typeof v === "boolean" ? (
                    <button type="button" onClick={() => set(k, !v)}
                      className={`flex h-8 w-full items-center rounded-lg border px-2 text-xs ${v ? "border-success/30 bg-success/10 text-success" : "bg-card text-muted-foreground"}`}>
                      <span className={`mr-2 h-3.5 w-3.5 rounded-full ${v ? "bg-success" : "bg-muted-foreground/40"}`} />
                      {v ? t("On — real market fills", "开启：按真实行情成交") : t("Off — agent supplies price", "关闭：由智能体提供价格")}
                    </button>
                  ) : SELECTS[k] ? (
                    <select value={String(v)} onChange={(e) => set(k, e.target.value)}
                      className="h-8 rounded-lg border bg-card px-2 text-sm">
                      {SELECTS[k].map((o) => <option key={o} value={o}>{OPTION_LABEL[o] ? t(OPTION_LABEL[o][0], OPTION_LABEL[o][1]) : o}</option>)}
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
          className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-primary disabled:opacity-50">
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : saved ? <Check className="h-4 w-4" /> : <Save className="h-4 w-4" />}
          {saved ? t("Saved", "已保存") : t("Save settings", "保存设置")}
        </button>
        <button onClick={resetDefaults} className="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm hover:bg-accent">
          <RotateCcw className="h-4 w-4" /> {t("Reset to defaults", "恢复默认")}
        </button>
        {msg && <span className="text-xs text-destructive">{msg}</span>}
      </div>
    </div>
  );
}
