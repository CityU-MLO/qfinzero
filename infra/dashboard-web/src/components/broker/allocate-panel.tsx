"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ChevronDown, ChevronRight, Loader2, RotateCcw } from "lucide-react";

import { createAccount, futuresSpecs, type FutureSpecRow } from "./api";

import { useT } from "@/components/locale-provider";

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-sm font-medium text-foreground">{label}</span>
      {children}
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </label>
  );
}

const inputCls =
  "rounded-md border border-input bg-card px-3 py-2 text-sm text-foreground outline-none focus:border-ring focus:ring-2 focus:ring-ring/20";
const cellInput = "w-24 rounded border border-input bg-card px-1.5 py-1 text-right text-[12px] outline-none focus:border-ring";
const COMMON = ["ES", "MES", "NQ", "MNQ", "CL", "GC", "ZN", "ZB", "6E"];

type Override = { rate?: string; fixed?: string };

/** Futures margin per root: built-in approximate rates, editable per account. */
function FuturesMargin({ overrides, setOverrides, callSessions, setCallSessions }: {
  overrides: Record<string, Override>;
  setOverrides: (o: Record<string, Override>) => void;
  callSessions: number;
  setCallSessions: (n: number) => void;
}) {
  const t = useT();
  const [specs, setSpecs] = useState<FutureSpecRow[]>([]);
  const [all, setAll] = useState(false);
  useEffect(() => {
    futuresSpecs().then((r) => setSpecs(r.specs)).catch(() => setSpecs([]));
  }, []);
  const rows = all ? specs : specs.filter((s) => COMMON.includes(s.root) || overrides[s.root]);
  const set = (root: string, k: keyof Override, v: string) => {
    const next = { ...overrides, [root]: { ...overrides[root], [k]: v } };
    if (!next[root].rate && !next[root].fixed) delete next[root];
    setOverrides(next);
  };
  return (
    <div className="rounded-lg border p-4">
      <div className="mb-1 text-sm font-medium text-foreground">{t("Futures margin", "期货保证金")}</div>
      <p className="mb-3 text-xs text-muted-foreground">
        {t("Futures trade in this account on margin: opening needs the initial margin free, positions settle daily, and a call is met at the initial margin. Built-in rates are approximations of CME levels; enter the exchange's requirement per contract to use it.",
          "期货在本账户中以保证金交易：开仓需要可用的初始保证金，持仓每日结算，追加保证金须补足到初始保证金。内置比例是 CME 水平的近似值；填入交易所公布的每手保证金即可使用真实数值。")}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead className="text-muted-foreground">
            <tr className="text-left">
              <th className="py-1 pr-2 font-medium">{t("Root", "品种")}</th>
              <th className="py-1 pr-2 font-medium">{t("Contract", "合约")}</th>
              <th className="py-1 pr-2 text-right font-medium">{t("Multiplier", "乘数")}</th>
              <th className="py-1 pr-2 text-right font-medium">{t("Maint. % of notional", "维持 % 名义价值")}</th>
              <th className="py-1 text-right font-medium">{t("or USD / contract", "或 美元/手")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => {
              const o = overrides[s.root] ?? {};
              return (
                <tr key={s.root} className="border-t">
                  <td className="py-1 pr-2 font-mono font-medium text-foreground">{s.root}</td>
                  <td className="py-1 pr-2 text-muted-foreground">{s.name}</td>
                  <td className="py-1 pr-2 text-right tabular-nums">{s.multiplier.toLocaleString()}</td>
                  <td className="py-1 pr-2 text-right">
                    <input className={cellInput} inputMode="decimal" value={o.rate ?? ""} placeholder={(s.margin_rate * 100).toFixed(1)}
                      onChange={(e) => set(s.root, "rate", e.target.value)} />
                  </td>
                  <td className="py-1 text-right">
                    <input className={cellInput} inputMode="decimal" value={o.fixed ?? ""} placeholder="—"
                      onChange={(e) => set(s.root, "fixed", e.target.value)} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="mt-2 flex items-center justify-between text-xs">
        <button type="button" onClick={() => setAll(!all)} className="flex items-center gap-1 text-muted-foreground hover:text-foreground">
          {all ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          {all ? t("Common contracts only", "只显示常用合约") : t(`All ${specs.length} contracts`, `全部 ${specs.length} 个合约`)}
        </button>
        {Object.keys(overrides).length > 0 && (
          <button type="button" onClick={() => setOverrides({})} className="flex items-center gap-1 text-muted-foreground hover:text-foreground">
            <RotateCcw className="h-3 w-3" /> {t("Use built-in rates", "恢复内置比例")}
          </button>
        )}
      </div>
      <label className="mt-3 flex items-center justify-between gap-3 text-sm">
        <span>
          {t("Unmet margin call", "未补足的追加保证金")}
          <span className="block text-xs text-muted-foreground">{t("Liquidate the futures after this many settlements.", "经过几次结算后强制平仓期货。")}</span>
        </span>
        <select value={callSessions} onChange={(e) => setCallSessions(Number(e.target.value))} className={inputCls}>
          <option value={0}>{t("Never liquidate", "从不强平")}</option>
          <option value={1}>{t("Next settlement", "下一次结算")}</option>
          <option value={2}>{t("After 2 settlements", "2 次结算后")}</option>
          <option value={3}>{t("After 3 settlements", "3 次结算后")}</option>
        </select>
      </label>
    </div>
  );
}

export function AllocatePanel({
  onBack,
  onCreated,
}: {
  onBack: () => void;
  onCreated: (accountId: string) => void;
}) {
  const t = useT();
  const [cash, setCash] = useState(100_000);
  const [market, setMarket] = useState("us");
  const [leverage, setLeverage] = useState(2);
  const [maintenance, setMaintenance] = useState(0.25);
  const [overrides, setOverrides] = useState<Record<string, Override>>({});
  const [callSessions, setCallSessions] = useState(1);
  const futureSpecs = useMemo(() => {
    const out: Record<string, Record<string, number>> = {};
    for (const [root, o] of Object.entries(overrides)) {
      const rate = parseFloat(o.rate ?? "");
      const fixed = parseFloat(o.fixed ?? "");
      if (Number.isFinite(fixed) && fixed > 0) out[root] = { maintenance_margin: fixed };
      else if (Number.isFinite(rate) && rate > 0) out[root] = { margin_rate: rate / 100 };
    }
    return out;
  }, [overrides]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setErr(null);
    try {
      const res = await createAccount({
        initial_cash: cash,
        market,
        // PMB's MarginConfig: Reg-T style stock ratios, futures overrides per root
        margin_config: {
          stock_initial: 1 / leverage,
          stock_maintenance: maintenance,
          future_specs: futureSpecs,
          future_margin_call_sessions: callSessions,
        },
      });
      onCreated(res.account_id);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex w-full max-w-lg flex-col">
      <button
        onClick={onBack}
        className="mb-6 flex w-fit items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> {t("Back", "返回")}
      </button>

      <h2 className="mb-1 text-xl font-semibold text-foreground">{t("Open an account", "开立账户")}</h2>
      <p className="mb-6 text-sm text-muted-foreground">
        {t(
          "Open a paper brokerage account with the capital and risk profile you want.",
          "按你需要的资金规模和风险设置，开立一个模拟券商账户。",
        )}
      </p>

      <div className="grid gap-5">
        <Field label={t("Starting capital (USD)", "初始资金（USD）")} hint={t("Cash the account opens with.", "账户开立时的现金。")}>
          <input
            type="number"
            min={1000}
            step={1000}
            value={cash}
            onChange={(e) => setCash(Number(e.target.value))}
            className={inputCls}
          />
        </Field>

        <Field label={t("Market", "市场")}>
          <select value={market} onChange={(e) => setMarket(e.target.value)} className={inputCls}>
            <option value="us">{t("US: stocks, options and CME futures", "美国：股票、期权和 CME 期货")}</option>
          </select>
        </Field>

        <div className="grid grid-cols-2 gap-4">
          <Field label={t("Stock leverage", "股票杠杆")} hint={t(`Buying power ≈ ${leverage}× equity`, `购买力 ≈ 权益的 ${leverage} 倍`)}>
            <select
              value={leverage}
              onChange={(e) => setLeverage(Number(e.target.value))}
              className={inputCls}
            >
              <option value={1}>{t("1× (cash)", "1×（现金）")}</option>
              <option value={2}>{t("2× (Reg-T)", "2×（Reg-T）")}</option>
              <option value={4}>{t("4× (day)", "4×（日内）")}</option>
            </select>
          </Field>
          <Field label={t("Stock maintenance", "股票维持保证金")} hint={t("Margin-call threshold for stocks.", "股票追加保证金的触发阈值。")}>
            <select
              value={maintenance}
              onChange={(e) => setMaintenance(Number(e.target.value))}
              className={inputCls}
            >
              <option value={0.25}>25%</option>
              <option value={0.3}>30%</option>
              <option value={0.4}>40%</option>
            </select>
          </Field>
        </div>

        <FuturesMargin overrides={overrides} setOverrides={setOverrides}
          callSessions={callSessions} setCallSessions={setCallSessions} />
      </div>

      {err && (
        <div className="mt-5 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          {err}
        </div>
      )}

      <button
        onClick={submit}
        disabled={busy}
        className="mt-6 flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 font-semibold text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
      >
        {busy && <Loader2 className="h-4 w-4 animate-spin" />}
        {t("Open account", "开立账户")}
      </button>
    </div>
  );
}
