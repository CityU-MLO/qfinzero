"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, Loader2, RefreshCw } from "lucide-react";

import { listAccounts, createSession, money, type AccountRow } from "./api";

const inputCls =
  "rounded-md border border-input bg-card px-3 py-2 text-sm text-foreground outline-none focus:border-ring focus:ring-2 focus:ring-ring/20";

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
    <div className="flex w-full max-w-lg flex-col">
      <button
        onClick={onBack}
        className="mb-6 flex w-fit items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> Back
      </button>

      <h2 className="mb-1 text-xl font-semibold text-foreground">Trade an account</h2>
      <p className="mb-6 text-sm text-muted-foreground">
        Choose an account and a trading day, then step onto the floor.
      </p>

      <div className="grid gap-5">
        <label className="flex flex-col gap-1.5">
          <span className="flex items-center justify-between text-sm font-medium text-foreground">
            Account
            <button
              onClick={refresh}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
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
            <div className="rounded-lg border border-dashed border-border px-3 py-2 text-sm text-muted-foreground">
              {loading ? "Loading…" : "No accounts yet — allocate one first."}
            </div>
          )}
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-medium text-foreground">Trading day (start date)</span>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            min="2017-01-01"
            max="2025-12-31"
            className={inputCls}
          />
          <span className="text-xs text-muted-foreground">
            The market opens on this date; you control the clock from there.
          </span>
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-medium text-foreground">Watchlist</span>
          <input
            value={symbols}
            onChange={(e) => setSymbols(e.target.value)}
            placeholder="AAPL, MSFT, NVDA"
            className={inputCls}
          />
          <span className="text-xs text-muted-foreground">Comma-separated tickers to trade.</span>
        </label>
      </div>

      {err && (
        <div className="mt-5 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          {err}
        </div>
      )}

      <button
        onClick={launch}
        disabled={busy || !accountId}
        className="mt-6 flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 font-semibold text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
      >
        {busy && <Loader2 className="h-4 w-4 animate-spin" />}
        {busy ? "Loading market data…" : "Open the market"}
      </button>
    </div>
  );
}
