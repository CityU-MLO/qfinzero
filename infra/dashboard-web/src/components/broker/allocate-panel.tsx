"use client";

import { useState } from "react";
import { ArrowLeft, Loader2 } from "lucide-react";

import { createAccount } from "./api";

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
      <span className="text-sm font-medium text-slate-200">{label}</span>
      {children}
      {hint && <span className="text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

const inputCls =
  "rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:border-emerald-500";

export function AllocatePanel({
  onBack,
  onCreated,
}: {
  onBack: () => void;
  onCreated: (accountId: string) => void;
}) {
  const [cash, setCash] = useState(100_000);
  const [market, setMarket] = useState("us");
  const [leverage, setLeverage] = useState(2);
  const [maintenance, setMaintenance] = useState(0.25);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setErr(null);
    try {
      const res = await createAccount({
        initial_cash: cash,
        market,
        margin_config: {
          initial_margin_ratio: 1 / leverage,
          maintenance_margin_ratio: maintenance,
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
    <div className="mx-auto flex min-h-full w-full max-w-lg flex-col justify-center px-6 py-12">
      <button
        onClick={onBack}
        className="mb-6 flex w-fit items-center gap-1.5 text-sm text-slate-400 hover:text-white"
      >
        <ArrowLeft className="h-4 w-4" /> Back
      </button>

      <h2 className="mb-1 text-2xl font-bold text-white">Allocate Account</h2>
      <p className="mb-8 text-sm text-slate-400">
        Open a paper brokerage account with the capital and risk profile you want.
      </p>

      <div className="grid gap-5">
        <Field label="Starting capital (USD)" hint="Cash the account opens with.">
          <input
            type="number"
            min={1000}
            step={1000}
            value={cash}
            onChange={(e) => setCash(Number(e.target.value))}
            className={inputCls}
          />
        </Field>

        <Field label="Market">
          <select value={market} onChange={(e) => setMarket(e.target.value)} className={inputCls}>
            <option value="us">US Equities</option>
          </select>
        </Field>

        <div className="grid grid-cols-2 gap-4">
          <Field label="Leverage" hint={`Buying power ≈ ${leverage}×`}>
            <select
              value={leverage}
              onChange={(e) => setLeverage(Number(e.target.value))}
              className={inputCls}
            >
              <option value={1}>1× (cash)</option>
              <option value={2}>2× (Reg-T)</option>
              <option value={4}>4× (day)</option>
            </select>
          </Field>
          <Field label="Maintenance margin" hint="Margin-call threshold.">
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
      </div>

      {err && (
        <div className="mt-5 rounded-lg border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-300">
          {err}
        </div>
      )}

      <button
        onClick={submit}
        disabled={busy}
        className="mt-8 flex items-center justify-center gap-2 rounded-lg bg-emerald-500 px-4 py-3 font-semibold text-slate-950 transition hover:bg-emerald-400 disabled:opacity-50"
      >
        {busy && <Loader2 className="h-4 w-4 animate-spin" />}
        Open account
      </button>
    </div>
  );
}
