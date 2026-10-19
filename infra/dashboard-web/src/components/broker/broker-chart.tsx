"use client";

// The broker's chart: history from before the session (time-locked to the
// session start, so nothing after the clock leaks in) joined to the bars the
// session has played, with fills marked on the candles, working limit orders
// and the position's average price as lines. Zoom and pan like QFZView; scroll
// left for older history.

import * as React from "react";

import { TradingChart, type Indicators, type PriceLineSpec, type TradeMark } from "@/components/charts/trading-chart";
import { useT } from "@/components/locale-provider";
import { aggregate, mergeBars, type Bar, type Interval } from "@/lib/bars";
import { addDays, loadBars } from "@/lib/qfzview";
import { cn } from "@/lib/utils";

import { etDate, instName, type OpenOrder, type Position, type Trade } from "./api";
import type { Candle } from "./candle-chart";

const BROKER_INTERVALS: Interval[] = [1, 5, 15, 60];

export function BrokerChart({ symbol, isFuture, candles, startTs, trades, orders, positions }: {
  symbol: string;
  isFuture: boolean;
  candles: Candle[];
  startTs: string | undefined;
  trades: Trade[];
  orders: OpenOrder[];
  positions: Position[];
}) {
  const t = useT();
  const [interval, setIntervalMin] = React.useState<Interval>(1);
  const [ind, setInd] = React.useState<Indicators>({ ma: [20], ema: [], bb: false, vwap: true });
  const [hist, setHist] = React.useState<{ key: string; bars: Bar[]; start: string | null; done: boolean }>({
    key: "", bars: [], start: null, done: false,
  });
  const loading = React.useRef(false);
  const qfz = isFuture ? `/${symbol}` : symbol;
  const key = `${qfz}|${startTs ?? ""}`;
  const keyRef = React.useRef(key);
  keyRef.current = key;

  const loadPage = React.useCallback(async (end: string) => {
    if (!startTs || loading.current) return;
    loading.current = true;
    const k = keyRef.current;
    try {
      // minute bars up to the session start only (as_of), a few days at a time
      const page = await loadBars(qfz, 1, end, startTs);
      if (keyRef.current !== k) return;
      setHist((h) => ({ key: k, bars: mergeBars(page.bars, h.key === k ? h.bars : []), start: page.start, done: !page.bars.length && h.key === k && !!h.start }));
    } catch {
      if (keyRef.current === k) setHist((h) => ({ ...h, key: k, done: true }));
    } finally {
      loading.current = false;
    }
  }, [qfz, startTs]);

  React.useEffect(() => {
    loading.current = false;
    setHist({ key, bars: [], start: null, done: false });
    if (startTs) void loadPage(etDate(startTs));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const older = React.useCallback(() => {
    if (hist.key === key && hist.start && !hist.done) void loadPage(addDays(hist.start, -1));
  }, [hist, key, loadPage]);

  const session: Bar[] = React.useMemo(() => candles.map((c) => ({
    ns: Date.parse(c.ts) * 1e6, day: etDate(c.ts), open: c.o, high: c.h, low: c.l, close: c.c, volume: c.v,
  })), [candles]);
  const bars = React.useMemo(() => {
    const before = hist.key === key ? hist.bars.filter((b) => !session.length || b.ns < session[0].ns) : [];
    return aggregate(mergeBars(before, session), interval, "et");
  }, [hist, key, session, interval]);

  const marks: TradeMark[] = React.useMemo(() => trades
    .filter((x) => x.ts && x.instrument_id && instName(String(x.instrument_id)).replace(/\.v\.\d+$/, "") === symbol)
    .map((x) => ({ ns: Date.parse(String(x.ts)) * 1e6, side: String(x.side).toUpperCase() === "BUY" ? "buy" as const : "sell" as const,
      text: `${String(x.side).toUpperCase() === "BUY" ? "B" : "S"} ${x.qty}@${Number(x.price).toFixed(2)}` })), [trades, symbol]);

  const lines: PriceLineSpec[] = React.useMemo(() => {
    const out: PriceLineSpec[] = [];
    for (const o of orders) {
      if (instName(o.instrument_id) !== symbol || o.limit_price == null) continue;
      out.push({ price: o.limit_price, title: `${o.side} ${o.qty} LMT`, tone: o.side.toUpperCase() === "BUY" ? "up" : "down", dashed: true });
    }
    const p = positions.find((x) => instName(x.instrument_id) === symbol && x.qty !== 0);
    if (p) out.push({ price: p.avg_price, title: `${t("AVG", "均价")} ${p.qty}`, tone: "accent" });
    return out;
  }, [orders, positions, symbol, t]);

  const btn = (on: boolean) => cn("rounded px-1.5 py-0.5 text-[11px] font-medium", on ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground");
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 pb-1">
        <div className="flex rounded-md border bg-background p-0.5">
          {BROKER_INTERVALS.map((i) => (
            <button key={i} onClick={() => setIntervalMin(i)} className={btn(interval === i)}>{i === 60 ? "1h" : `${i}m`}</button>
          ))}
        </div>
        <div className="flex gap-1">
          <button onClick={() => setInd({ ...ind, ma: ind.ma.length ? [] : [20] })} className={btn(ind.ma.length > 0)}>MA20</button>
          <button onClick={() => setInd({ ...ind, vwap: !ind.vwap })} className={btn(ind.vwap)}>VWAP</button>
          <button onClick={() => setInd({ ...ind, bb: !ind.bb })} className={btn(ind.bb)}>BB</button>
        </div>
        <span className="ml-auto text-[11px] text-muted-foreground">
          {t("History before the session start · scroll to zoom, drag to pan", "会话开始前的历史 · 滚轮缩放，拖动平移")}
        </span>
      </div>
      <div className="min-h-0 flex-1">
        <TradingChart bars={bars} zone="et" indicators={ind} marks={marks} priceLines={lines} onNeedOlder={older}
                      follow viewKey={`${key}|${interval}`}
                      empty={t("Press Start to play the session.", "点击“开始”播放会话。")} />
      </div>
    </div>
  );
}
