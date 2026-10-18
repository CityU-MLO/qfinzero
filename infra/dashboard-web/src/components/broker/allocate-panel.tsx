"use client";

import { useState } from "react";
import { ArrowLeft, Loader2 } from "lucide-react";

import { createAccount } from "./api";

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
            <option value="us">{t("US Equities", "美股")}</option>
          </select>
        </Field>

        <div className="grid grid-cols-2 gap-4">
          <Field label={t("Leverage", "杠杆")} hint={t(`Buying power ≈ ${leverage}×`, `购买力 ≈ ${leverage}×`)}>
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
          <Field label={t("Maintenance margin", "维持保证金")} hint={t("Margin-call threshold.", "追加保证金的触发阈值。")}>
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
        {t("Open account", "开立账户")}
      </button>
    </div>
  );
}
