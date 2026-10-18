"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, Loader2, RefreshCw } from "lucide-react";

import { listAccounts, createSession, money, type AccountRow } from "./api";

import { useT } from "@/components/locale-provider";

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
  const t = useT();
  const [accounts, setAccounts] = useState<AccountRow[]>([]);
  const [accountId, setAccountId] = useState(presetAccountId ?? "");
  const [date, setDate] = useState("");
  const [minuteRange, setMinuteRange] = useState<{ start: string; end: string } | null>(null);
  const [symbols, setSymbols] = useState("SPY,QQQ,NVDA,AAPL");
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
    // default to the latest day with minute bars, so the session has data
    fetch("/api/coverage/extent")
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { stores?: { minute?: { start: string; end: string } | null; daily?: { end: string } | null } } | null) => {
        const m = d?.stores?.minute;
        if (m) setMinuteRange({ start: m.start, end: m.end });
        setDate((cur) => cur || m?.end || d?.stores?.daily?.end || new Date().toISOString().slice(0, 10));
      })
      .catch(() => setDate((cur) => cur || new Date().toISOString().slice(0, 10)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function launch() {
    setErr(null);
    const watchlist = symbols
      .split(",")
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean);
    if (!accountId) return setErr(t("Select an account first.", "请先选择一个账户。"));
    if (!watchlist.length) return setErr(t("Add at least one symbol.", "请至少添加一个代码。"));
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
        <ArrowLeft className="h-4 w-4" /> {t("Back", "返回")}
      </button>

      <h2 className="mb-1 text-xl font-semibold text-foreground">{t("Trade an account", "交易账户")}</h2>
      <p className="mb-6 text-sm text-muted-foreground">
        {t("Choose an account and a trading day, then step onto the floor.", "选择一个账户和交易日，然后进入交易。")}
      </p>

      <div className="grid gap-5">
        <label className="flex flex-col gap-1.5">
          <span className="flex items-center justify-between text-sm font-medium text-foreground">
            {t("Account", "账户")}
            <button
              onClick={refresh}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            >
              <RefreshCw className={loading ? "h-3 w-3 animate-spin" : "h-3 w-3"} /> {t("refresh", "刷新")}
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
              {loading ? t("Loading…", "加载中…") : t("No accounts yet — allocate one first.", "还没有账户，请先开立一个。")}
            </div>
          )}
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-medium text-foreground">{t("Trading day (start date)", "交易日（开始日期）")}</span>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className={inputCls}
          />
          <span className="text-xs text-muted-foreground">
            {t("The market opens on this date; you control the clock from there.", "市场在这一天开盘，之后的时钟由你控制。")}
            {minuteRange && (
              <> {t(`Minute data: ${minuteRange.start} → ${minuteRange.end}.`, `分钟数据范围：${minuteRange.start} → ${minuteRange.end}。`)}</>
            )}
          </span>
          {minuteRange && date && (date < minuteRange.start || date > minuteRange.end) && (
            <span className="text-xs text-warning">
              {t("No minute bars on this date: the session will have nothing to trade.", "这一天没有分钟数据，会话中将无法交易。")}
            </span>
          )}
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="text-sm font-medium text-foreground">{t("Watchlist", "自选")}</span>
          <input
            value={symbols}
            onChange={(e) => setSymbols(e.target.value)}
            placeholder="AAPL, MSFT, NVDA"
            className={inputCls}
          />
          <span className="text-xs text-muted-foreground">{t("Comma-separated tickers to trade.", "要交易的代码，用逗号分隔。")}</span>
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
        {busy ? t("Loading market data…", "正在加载行情数据…") : t("Open the market", "开盘")}
      </button>
    </div>
  );
}
