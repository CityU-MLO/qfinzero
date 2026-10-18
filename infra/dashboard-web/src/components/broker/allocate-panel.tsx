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
      <span className="text-sm font-medium text-foreground">{label}</span>
      {children}
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </label>
  );
}

const inputCls =
  "rounded-md border border-input bg-card px-3 py-2 text-sm text-foreground outline-none focus:border-ring focus:ring-2 focus:ring-ring/20";

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
    <div className="flex w-full max-w-lg flex-col">
      <button
        onClick={onBack}
        className="mb-6 flex w-fit items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> Back
      </button>

      <h2 className="mb-1 text-xl font-semibold text-foreground">Open an account</h2>
      <p className="mb-6 text-sm text-muted-foreground">
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
        Open account
      </button>
    </div>
  );
}
