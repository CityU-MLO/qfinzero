"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";

import { sessionOptionChain, num, type ChainResponse, type ChainLeg } from "./api";

import { useT } from "@/components/locale-provider";

export function OptionChain({
  sessionId,
  underlying,
  clockIndex,
  onTrade,
}: {
  sessionId: string;
  underlying: string;
  clockIndex: number;
  onTrade: (contract: string, side: "BUY" | "SELL") => void;
}) {
  const t = useT();
  const [chain, setChain] = useState<ChainResponse | null>(null);
  const [expiry, setExpiry] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const busyRef = useRef(false);
  const prevLast = useRef<Record<string, number>>({});
  const reloadRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [flash, setFlash] = useState<Record<string, "up" | "down">>({});
  const [poll, setPoll] = useState(0);
  const [greeks, setGreeks] = useState(true);

  // Re-fetch on underlying/expiry change and every clock step (flash). Skips if a
  // request is in flight, so it self-throttles to backend latency. When the
  // backend is still loading minute bars in the background, re-poll shortly to
  // upgrade the skeleton marks to live ones.
  useEffect(() => {
    let cancelled = false;
    if (busyRef.current) return;
    busyRef.current = true;
    if (!chain) setLoading(true);
    sessionOptionChain(sessionId, underlying, expiry || undefined)
      .then((c) => {
        if (cancelled) return;
        const f: Record<string, "up" | "down"> = {};
        for (const row of c.rows) {
          for (const leg of [row.call, row.put]) {
            if (!leg?.contract || leg.last == null) continue;
            const p = prevLast.current[leg.contract];
            if (p != null && leg.last !== p) f[leg.contract] = leg.last > p ? "up" : "down";
            prevLast.current[leg.contract] = leg.last;
          }
        }
        setFlash(f);
        setChain(c);
        if (!expiry && c.expiry) setExpiry(c.expiry);
        setErr(null);
        // background load still running → poll again to pick up live marks
        if (c.loading) {
          if (reloadRef.current) clearTimeout(reloadRef.current);
          reloadRef.current = setTimeout(() => setPoll((p) => p + 1), 600);
        }
      })
      .catch((e) => !cancelled && setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => {
        busyRef.current = false;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, underlying, expiry, clockIndex, poll]);

  useEffect(
    () => () => {
      if (reloadRef.current) clearTimeout(reloadRef.current);
    },
    [],
  );

  const rows = chain?.rows ?? [];
  const missingRate = rows.some((r) => r.call?.greek_status === "missing_rate" || r.put?.greek_status === "missing_rate");
  const spot = chain?.spot ?? undefined;
  const atmStrike =
    spot != null && rows.length
      ? rows.reduce((b, r) => (Math.abs(r.strike - spot) < Math.abs(b.strike - spot) ? r : b)).strike
      : null;

  return (
    <div className="broker-panel flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-2">
        <div className="text-sm font-semibold text-foreground">
          {underlying} <span className="text-muted-foreground">{t("options", "期权")}</span>
        </div>
        <select
          value={expiry}
          onChange={(e) => {
            setExpiry(e.target.value);
            setChain(null);
          }}
          className="rounded-lg border border-border bg-background px-2 py-1 text-xs text-foreground"
        >
          {(chain?.expiries ?? []).map((x) => (
            <option key={x} value={x}>
              {t("exp", "到期")} {x}
            </option>
          ))}
        </select>
        {spot != null && (
          <span className="font-mono text-xs text-muted-foreground">
            {t("spot", "现价")} <span className="text-foreground">{num(spot)}</span>
          </span>
        )}
        <span className="flex items-center gap-1 text-[11px] text-up">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-up" /> {t("live · minute", "实时 · 分钟")}
        </span>
        {loading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
        <button onClick={() => setGreeks(!greeks)}
                className={`ml-auto rounded-md border px-2 py-0.5 text-[11px] ${greeks ? "border-primary bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted"}`}>
          Greeks
        </button>
      </div>
      {greeks && missingRate && (
        <div className="border-b border-border bg-warning/10 px-4 py-1.5 text-[11px] text-warning">
          {t("No interest rate for this date, so Greeks cannot be computed. ", "此日期没有利率数据，无法计算 Greeks。")}
          <a href="/settings#rates" className="font-medium underline">{t("Load a rate file in Settings", "到设置中加载利率文件")}</a>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto font-mono text-xs">
        {err && <div className="p-4 text-down">{err}</div>}
        {!err && !rows.length && !loading && (
          <div className="p-6 text-center text-muted-foreground">{t("No chain for this underlying/date.", "该标的/日期没有期权链。")}</div>
        )}
        {!!rows.length && (
          <table className="w-full">
            <thead className="sticky top-0 z-10 bg-background text-[10px] text-muted-foreground">
              <tr>
                <th className="py-1 text-center text-up" colSpan={greeks ? 10 : 5}>
                  {t("Calls", "看涨")}
                </th>
                <th className="py-1 text-center">{t("Strike", "行权价")}</th>
                <th className="py-1 text-center text-down" colSpan={greeks ? 10 : 5}>
                  {t("Puts", "看跌")}
                </th>
              </tr>
              <tr className="text-right text-muted-foreground">
                <th className="px-1"></th>
                {greeks && ["ν", "Θ", "Γ", "Δ", "IV"].map((g) => <th key={`c${g}`} className="px-1">{g}</th>)}
                <th className="px-1">{t("Bid", "买价")}</th>
                <th className="px-1">{t("Ask", "卖价")}</th>
                <th className="px-1">{t("Last", "最新价")}</th>
                <th className="px-1">{t("Vol", "成交量")}</th>
                <th className="px-1 text-center"></th>
                <th className="px-1">{t("Last", "最新价")}</th>
                <th className="px-1">{t("Bid", "买价")}</th>
                <th className="px-1">{t("Ask", "卖价")}</th>
                <th className="px-1">{t("Vol", "成交量")}</th>
                {greeks && ["IV", "Δ", "Γ", "Θ", "ν"].map((g) => <th key={`p${g}`} className="px-1">{g}</th>)}
                <th className="px-1"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const atm = r.strike === atmStrike;
                return (
                  <tr key={r.strike} className={atm ? "bg-muted" : "hover:bg-muted"}>
                    <Side leg={r.call} side="call" flash={flash} onTrade={onTrade} greeks={greeks} />
                    <td className={`px-2 py-1 text-center font-semibold ${atm ? "text-warning" : "text-foreground"}`}>
                      {num(r.strike)}
                    </td>
                    <Side leg={r.put} side="put" flash={flash} onTrade={onTrade} greeks={greeks} />
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function Side({
  leg,
  side,
  flash,
  onTrade,
  greeks,
}: {
  leg: ChainLeg | null;
  side: "call" | "put";
  flash: Record<string, "up" | "down">;
  onTrade: (contract: string, s: "BUY" | "SELL") => void;
  greeks: boolean;
}) {
  const t = useT();
  if (!leg) {
    return (
      <>
        {Array.from({ length: greeks ? 10 : 5 }).map((_, i) => (
          <td key={i} className="px-1 py-1 text-right text-muted-foreground">
            —
          </td>
        ))}
      </>
    );
  }
  const dir = leg.contract ? flash[leg.contract] : undefined;
  const lastCls =
    dir === "up"
      ? "bg-up/25 text-up"
      : dir === "down"
        ? "bg-down/25 text-down"
        : leg.live
          ? "text-white"
          : "text-muted-foreground";
  const bs = (
    <span className="inline-flex gap-0.5">
      <button
        onClick={() => leg.contract && onTrade(leg.contract, "BUY")}
        title={t("Buy", "买入")}
        className="broker-btn rounded-sm bg-up/10 px-1 text-up hover:bg-up hover:text-white"
      >
        {t("B", "买")}
      </button>
      <button
        onClick={() => leg.contract && onTrade(leg.contract, "SELL")}
        title={t("Sell", "卖出")}
        className="broker-btn rounded-sm bg-down/10 px-1 text-down hover:bg-down hover:text-white"
      >
        {t("S", "卖")}
      </button>
    </span>
  );
  const cBid = (
    <td key="bid" className="px-1 py-1 text-right text-muted-foreground">
      {leg.bid != null ? num(leg.bid) : "—"}
    </td>
  );
  const cAsk = (
    <td key="ask" className="px-1 py-1 text-right text-muted-foreground">
      {leg.ask != null ? num(leg.ask) : "—"}
    </td>
  );
  const cLast = (
    <td key="last" className={`px-1 py-1 text-right transition-colors ${lastCls}`}>
      {leg.last != null ? num(leg.last) : "—"}
    </td>
  );
  const cVol = (
    <td key="vol" className="px-1 py-1 text-right text-muted-foreground">
      {leg.volume?.toLocaleString?.() ?? "—"}
    </td>
  );
  const trade = (
    <td key="bs" className="px-1 py-1 text-center">
      {bs}
    </td>
  );
  const g = (key: string, v: number | null | undefined, f: (x: number) => string) => (
    <td key={key} title={leg.greeks === "day" ? t("Day close value (no live Greeks at this bar)", "当日收盘值（此刻无实时 Greeks）") : undefined}
        className={`px-1 py-1 text-right ${leg.greeks === "live" ? "text-foreground" : "text-muted-foreground/60"}`}>
      {v != null ? f(v) : "—"}
    </td>
  );
  const gIv = g("iv", leg.iv, (x) => `${(x * 100).toFixed(1)}%`);
  const gD = g("delta", leg.delta, (x) => x.toFixed(2));
  const gG = g("gamma", leg.gamma, (x) => x.toFixed(4));
  const gT = g("theta", leg.theta, (x) => x.toFixed(2));
  const gV = g("vega", leg.vega, (x) => x.toFixed(2));
  // Call: [BS] (ν Θ Γ Δ IV) Bid Ask Last Vol  ·  Put: Last Bid Ask Vol (IV Δ Γ Θ ν) [BS]
  const callCells = greeks ? [trade, gV, gT, gG, gD, gIv, cBid, cAsk, cLast, cVol] : [trade, cBid, cAsk, cLast, cVol];
  const putCells = greeks ? [cLast, cBid, cAsk, cVol, gIv, gD, gG, gT, gV, trade] : [cLast, cBid, cAsk, cVol, trade];
  return <>{side === "call" ? callCells : putCells}</>;
}
