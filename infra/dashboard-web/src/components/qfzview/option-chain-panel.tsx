"use client";

// QFZView's option chain: one expiry of an underlying as it stood at a moment
// (UPQ /option/chain_snapshot), calls on the left and puts on the right of the
// strike, with bid/ask, last trade, volume, IV and delta. Clicking a contract
// charts it. The day and time are ET; the days offered are those the store has
// the underlying's option minutes for, the latest on or before the chart's day first.

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, X } from "lucide-react";

import { useT } from "@/components/locale-provider";
import {
  etToUtcIso, loadChain, loadExpiries, loadOptionDays, loadSpot, parseOption, type ChainLeg, type ChainRow,
} from "@/lib/qfzview";
import { cn } from "@/lib/utils";

const fmt = (v: number | null | undefined, d = 2) => (v == null ? "—" : v.toFixed(d));
const fmtVol = (v: number | null | undefined) => (v == null || v === 0 ? "—" : v.toLocaleString());

export function OptionChainPanel({ underlying, highlight, defaultDay, range, onPick, onClose }: {
  underlying: string;
  /** contract to mark (the one being charted) */
  highlight?: string;
  defaultDay: string;
  /** days the store has option minutes for */
  range?: { start: string; end: string } | null;
  onPick: (contract: string) => void;
  onClose: () => void;
}) {
  const t = useT();
  const [picked, setPicked] = React.useState("");
  const [time, setTime] = React.useState("15:59");
  const [expiry, setExpiry] = React.useState("");
  const [width, setWidth] = React.useState(12);           // strikes each side of the money
  const days = useQuery({
    queryKey: ["qfzview", "optdays", underlying, range?.start, range?.end],
    queryFn: () => loadOptionDays(underlying, range!.start, range!.end), enabled: !!range, staleTime: 5 * 60_000,
  });
  React.useEffect(() => setPicked(""), [underlying, defaultDay]);
  // the chosen day, else the latest day with options on or before the chart's day, else the latest
  const day = picked || days.data?.find((d) => d <= defaultDay) || days.data?.[0] || defaultDay;
  React.useEffect(() => setExpiry(""), [underlying, day]);

  const spot = useQuery({ queryKey: ["qfzview", "spot", underlying, day], queryFn: () => loadSpot(underlying, day),
    staleTime: 5 * 60_000 });
  const expiries = useQuery({
    queryKey: ["qfzview", "expiries", underlying, day, spot.data ?? null],
    queryFn: () => loadExpiries(underlying, day, spot.data ?? null),
    enabled: spot.isFetched, staleTime: 5 * 60_000,
  });
  // the charted contract's expiry when it traded that day, else the nearest
  const hlExpiry = highlight ? parseOption(highlight)?.expiry ?? "" : "";
  const chosen = expiry || (expiries.data?.includes(hlExpiry) ? hlExpiry : expiries.data?.[0] ?? "");
  const at = etToUtcIso(day, time);
  const chain = useQuery({ queryKey: ["qfzview", "chain", underlying, at, chosen], queryFn: () => loadChain(underlying, at, chosen),
    enabled: !!chosen, staleTime: 60_000 });

  // strikes around the money (by spot; the middle of the chain without one)
  const rows: ChainRow[] = React.useMemo(() => {
    const all = chain.data ?? [];
    if (!all.length) return all;
    const s = spot.data;
    let mid = Math.floor(all.length / 2);
    if (s != null) mid = all.reduce((b, r, i) => (Math.abs(r.strike - s) < Math.abs(all[b].strike - s) ? i : b), 0);
    return all.slice(Math.max(0, mid - width), mid + width + 1);
  }, [chain.data, spot.data, width]);
  const atm = spot.data != null && rows.length
    ? rows.reduce((b, r) => (Math.abs(r.strike - spot.data!) < Math.abs(b.strike - spot.data!) ? r : b)).strike : null;
  const outOfRange = range && (day < range.start || day > range.end);

  const Leg = ({ leg, side, itm }: { leg?: ChainLeg; side: "call" | "put"; itm: boolean }) => {
    const cells = leg ? [fmt(leg.bid), fmt(leg.ask), fmt(leg.last), fmtVol(leg.volume),
      leg.iv != null ? `${(leg.iv * 100).toFixed(0)}%` : "—", fmt(leg.delta)] : ["", "", "", "", "", ""];
    const ordered = side === "call" ? cells : [...cells].reverse();
    return (
      <>
        {ordered.map((c, i) => (
          <td key={i} onClick={leg ? () => onPick(leg.ticker) : undefined}
              className={cn("px-1.5 py-1 text-right tabular-nums", leg && "cursor-pointer hover:bg-primary/10",
                itm && "bg-foreground/[0.04]", leg?.ticker === highlight && "bg-primary/15 font-semibold text-foreground")}>
            {c}
          </td>
        ))}
      </>
    );
  };

  const head = [t("Bid", "买价"), t("Ask", "卖价"), t("Last", "最新"), t("Vol", "成交量"), "IV", "Δ"];
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <span className="text-[12px] font-semibold uppercase tracking-wide text-muted-foreground">
          {underlying} {t("option chain", "期权链")}
        </span>
        <button onClick={onClose} aria-label={t("Close", "关闭")} className="text-muted-foreground hover:text-foreground"><X className="h-4 w-4" /></button>
      </div>
      <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2 text-[12px]">
        <select value={day} onChange={(e) => setPicked(e.target.value)} className="h-7 rounded-md border bg-background px-1.5 font-mono"
                title={t("Days with option minutes for this underlying", "这个标的有期权分钟数据的日期")}>
          {(days.data?.length ? days.data : [day]).map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <input type="time" value={time} min="09:30" max="16:15" onChange={(e) => e.target.value && setTime(e.target.value)}
               className="h-7 rounded-md border bg-background px-1.5 font-mono" />
        <span className="text-muted-foreground">ET</span>
        <select value={chosen} onChange={(e) => setExpiry(e.target.value)} className="h-7 rounded-md border bg-background px-1.5 font-mono">
          {(expiries.data ?? []).map((x) => <option key={x} value={x}>{t("exp", "到期")} {x}</option>)}
        </select>
        <select value={width} onChange={(e) => setWidth(Number(e.target.value))} className="h-7 rounded-md border bg-background px-1.5">
          {[6, 12, 25, 1000].map((n) => <option key={n} value={n}>{n >= 1000 ? t("all strikes", "全部行权价") : t(`±${n} strikes`, `±${n} 档`)}</option>)}
        </select>
        {spot.data != null && <span className="font-mono text-muted-foreground">{t("spot", "现价")} <b className="text-foreground">{spot.data.toFixed(2)}</b></span>}
        {(chain.isFetching || expiries.isFetching) && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {rows.length ? (
          <table className="w-full font-mono text-[11px]">
            <thead className="sticky top-0 bg-card text-muted-foreground">
              <tr>
                <th colSpan={6} className="py-1 text-center font-semibold text-up">{t("Calls", "看涨")}</th>
                <th />
                <th colSpan={6} className="py-1 text-center font-semibold text-down">{t("Puts", "看跌")}</th>
              </tr>
              <tr className="border-b">
                {head.map((h) => <th key={`c${h}`} className="px-1.5 pb-1 text-right font-normal">{h}</th>)}
                <th className="px-2 pb-1 text-center font-normal">{t("Strike", "行权价")}</th>
                {[...head].reverse().map((h) => <th key={`p${h}`} className="px-1.5 pb-1 text-right font-normal">{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.strike} className={cn("border-b border-border/50", r.strike === atm && "border-y border-primary/40")}>
                  <Leg leg={r.call} side="call" itm={spot.data != null && r.strike < spot.data} />
                  <td className={cn("px-2 py-1 text-center font-semibold", r.strike === atm ? "text-primary" : "text-foreground")}>{r.strike}</td>
                  <Leg leg={r.put} side="put" itm={spot.data != null && r.strike > spot.data} />
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="flex h-full items-center justify-center p-6 text-center text-[12px] text-muted-foreground">
            {chain.isFetching || expiries.isFetching || spot.isFetching || days.isFetching ? <Loader2 className="h-5 w-5 animate-spin" />
              : days.isFetched && !days.data?.length ? t(`The store has no option minutes for ${underlying}.`, `存储中没有 ${underlying} 的期权分钟数据。`)
              : outOfRange ? t(`The store has option minutes from ${range!.start} to ${range!.end}.`, `存储中的期权分钟数据范围是 ${range!.start} 到 ${range!.end}。`)
                : !expiries.data?.length ? t(`No ${underlying} options traded on ${day}.`, `${underlying} 在 ${day} 没有期权成交。`)
                  : t("No contracts at this time.", "这个时间没有合约数据。")}
          </div>
        )}
      </div>
      <p className="border-t px-3 py-2 text-[11px] text-muted-foreground">
        {t("As of the chosen ET minute: last trade and volume so far, the latest quote, IV and delta off the mid (or the last trade). Click a contract to chart it.",
           "按所选美东时间：最新成交和当日累计成交量、最新报价，IV 和 Delta 按中间价（没有报价时按最新成交价）计算。点击合约查看它的 K 线。")}
      </p>
    </div>
  );
}
