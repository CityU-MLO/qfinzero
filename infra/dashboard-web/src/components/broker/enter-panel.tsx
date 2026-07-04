"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, Loader2, RefreshCw } from "lucide-react";

import { listAccounts, createSession, money, type AccountRow } from "./api";

const inputCls =
  "rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:border-sky-500";

export function EnterPanel({
  presetAccountId,
  onBack,
  onEnter,
}: {
  presetAccountId?: string | null;
  onBack: () => void;
  onEnter: (p: {
    sessionId: string;
    accountId: string;
    watchlist: string[];
  }) => void;
}) {
  const [accounts, setAccounts] = useState<AccountRow[]>([]);
  const [accountId, setAccountId] = useState(presetAccountId ?? "");
  const [date, setDate] = useState("2024-03-22");
  const [symbols, setSymbols] = useState("AAPL,MSFT,NVDA,TSLA");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      const { accounts } = await listAccounts();
      setAccounts(accounts);
      if (!accountId && accounts.length) setAccountId(accounts[0].account_id);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function launch() {
    setErr(null);
    const watchlist = symbols
      .split(",")
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean);
    if (!accountId) return setErr("Select an account first.");
    if (!watchlist.length) return setErr("Add at least one symbol.");
    setBusy(true);
    try {
      const { session_id } = await createSession({
        account_id: accountId,
        start_ts: `${date}T00:00:00`,
        end_ts: `${date}T23:59:59`,
        stocks: watchlist,
      });
      onEnter({ sessionId: session_id, accountId, watchlist });
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

      <h2 className="mb-1 text-2xl font-bold text-white">Enter Account</h2>
      <p className="mb-8 text-sm text-slate-400">
        Choose an account and a trading day, then step onto the floor.
      </p>

      <div className="grid gap-5">
        <label className="flex flex-col gap-1.5">
          <span className="flex items-center justify-between text-sm font-medium text-slate-200">
            Account
            <button
              onClick={refresh}
              className="flex items-center gap-1 text-xs text-slate-400 hover:text-white"
            >
              <RefreshCw className={loading ? "h-3 w-3 animate-spin" : "h-3 w-3"} /> refresh
            </button>
          </span>
          {accounts.length ? (
            <select
              value={accountId}
              onChange={(e) => setAccountId(e.target.value)}
              className={inputCls}
            >
              {accounts.map((a) => (
                <option key={a.account_id} value={a.account_id}>
                  {a.account_id} · {money(a.initial_cash)} · {a.market.toUpperCase()}
                </option>
              ))}
            </select>
          ) : (
            <div className="rounded-lg border border-dashed border-slate-700 px-3 py-2 text-sm text-slate-500">
              {loading ? "Loading…" : "No accounts yet — allocate one first."}
            </div>
          )}
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-medium text-slate-200">Trading day (start date)</span>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            min="2017-01-01"
            max="2025-12-31"
            className={inputCls}
          />
          <span className="text-xs text-slate-500">
            The market opens on this date; you control the clock from there.
          </span>
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-medium text-slate-200">Watchlist</span>
          <input
            value={symbols}
            onChange={(e) => setSymbols(e.target.value)}
            placeholder="AAPL, MSFT, NVDA"
            className={inputCls}
          />
          <span className="text-xs text-slate-500">Comma-separated tickers to trade.</span>
        </label>
      </div>

      {err && (
        <div className="mt-5 rounded-lg border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-300">
          {err}
        </div>
      )}

      <button
        onClick={launch}
        disabled={busy || !accountId}
        className="mt-8 flex items-center justify-center gap-2 rounded-lg bg-sky-500 px-4 py-3 font-semibold text-slate-950 transition hover:bg-sky-400 disabled:opacity-50"
      >
        {busy && <Loader2 className="h-4 w-4 animate-spin" />}
        {busy ? "Loading market data…" : "Open the market"}
      </button>
    </div>
  );
}
