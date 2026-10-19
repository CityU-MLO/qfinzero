"use client";

// The trading chart shared by QFZView and the broker: candles and volume,
// zoom (wheel, pinch) and pan, crosshair legend, moving averages, Bollinger
// bands, VWAP, trade markers, price lines (orders, average price) and extra
// line overlays (bid/ask). Built on TradingView's lightweight-charts.

import * as React from "react";
import {
  CandlestickSeries, createChart, createSeriesMarkers, HistogramSeries, LineSeries, LineStyle,
  type IChartApi, type IPriceLine, type ISeriesApi, type ISeriesMarkersPluginApi, type LogicalRange,
  type MouseEventParams, type SeriesMarker, type Time, type UTCTimestamp,
} from "lightweight-charts";

import { bollinger, chartTime, dayTime, ema, sma, vwap, type Bar, type Zone } from "@/lib/bars";
import { cn } from "@/lib/utils";

export interface Indicators { ma: number[]; ema: number[]; bb: boolean; vwap: boolean }
export const DEFAULT_INDICATORS: Indicators = { ma: [20], ema: [], bb: false, vwap: false };

export interface TradeMark { ns: number; side: "buy" | "sell"; text?: string }
export interface PriceLineSpec { price: number; title: string; tone: "up" | "down" | "accent" | "muted"; dashed?: boolean }
export interface Overlay { id: string; title: string; tone: "up" | "down" | "accent" | "muted"; points: { ns: number; value: number }[] }

/** A CSS colour from a design token (canvas needs concrete colours). */
function tokenColor(name: string, alpha = 1): string {
  if (typeof document === "undefined") return "#888";
  const el = document.createElement("span");
  el.style.color = `hsl(var(--${name}) / ${alpha})`;
  document.body.appendChild(el);
  const c = getComputedStyle(el).color;
  el.remove();
  return c || "#888";
}

function palette() {
  return {
    up: tokenColor("up"), down: tokenColor("down"), upVol: tokenColor("up", 0.35), downVol: tokenColor("down", 0.35),
    text: tokenColor("muted-foreground"), grid: tokenColor("border", 0.6), border: tokenColor("border"),
    bg: tokenColor("card"), accent: tokenColor("primary"), muted: tokenColor("muted-foreground", 0.8),
    lines: [tokenColor("chart-3"), tokenColor("chart-1"), tokenColor("chart-4"), tokenColor("chart-2"), tokenColor("chart-5")],
  };
}

/** Price decimals from the typical price: FX needs 5, BTC needs 2. */
function precisionFor(bars: Bar[]): number {
  const p = bars.length ? Math.abs(bars[bars.length - 1].close) : 100;
  if (p === 0) return 2;
  if (p < 0.01) return 6;
  if (p < 2) return 5;
  if (p < 10) return 4;
  return 2;
}

export interface TradingChartProps {
  bars: Bar[];
  daily?: boolean;
  zone?: Zone;
  indicators?: Indicators;
  marks?: TradeMark[];
  priceLines?: PriceLineSpec[];
  overlays?: Overlay[];
  /** called when the view reaches the first loaded bar (load older data) */
  onNeedOlder?: () => void;
  /** keep the latest bar in view as bars are appended (replays) */
  follow?: boolean;
  className?: string;
  empty?: React.ReactNode;
  /** changes when the symbol or interval changes: the view is reset */
  viewKey?: string;
}

export function TradingChart({
  bars, daily = false, zone = "et", indicators = DEFAULT_INDICATORS, marks = [], priceLines = [], overlays = [],
  onNeedOlder, follow = false, className, empty, viewKey = "",
}: TradingChartProps) {
  const host = React.useRef<HTMLDivElement>(null);
  const chartRef = React.useRef<IChartApi | null>(null);
  const candles = React.useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volume = React.useRef<ISeriesApi<"Histogram"> | null>(null);
  const lines = React.useRef<ISeriesApi<"Line">[]>([]);
  const markers = React.useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const pls = React.useRef<IPriceLine[]>([]);
  const colors = React.useRef<ReturnType<typeof palette> | null>(null);
  const older = React.useRef(onNeedOlder);
  older.current = onNeedOlder;
  const firstNs = React.useRef<number | null>(null);
  const lastKey = React.useRef<string | null>(null);
  const [legend, setLegend] = React.useState<Bar | null>(null);

  const t = React.useCallback((b: { ns: number; day?: string }) =>
    (daily ? dayTime(b.day ?? new Date(b.ns / 1e6).toISOString().slice(0, 10)) : chartTime(b.ns, zone)) as UTCTimestamp,
  [daily, zone]);

  // create once
  React.useEffect(() => {
    if (!host.current) return;
    const c = palette();
    colors.current = c;
    const chart = createChart(host.current, {
      autoSize: true,
      layout: { background: { color: c.bg }, textColor: c.text, fontSize: 11, attributionLogo: true },
      grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
      rightPriceScale: { borderColor: c.border, scaleMargins: { top: 0.08, bottom: 0.25 } },
      timeScale: { borderColor: c.border, timeVisible: true, secondsVisible: false, rightOffset: 4 },
      crosshair: { mode: 0 },
    });
    candles.current = chart.addSeries(CandlestickSeries, {
      upColor: c.up, downColor: c.down, borderUpColor: c.up, borderDownColor: c.down, wickUpColor: c.up, wickDownColor: c.down,
    });
    volume.current = chart.addSeries(HistogramSeries, { priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    markers.current = createSeriesMarkers(candles.current, []);
    chartRef.current = chart;

    const onRange = (r: LogicalRange | null) => {
      if (r && r.from < 5 && older.current) older.current();
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(onRange);
    return () => {
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(onRange);
      chart.remove();
      chartRef.current = null;
      candles.current = null;
      volume.current = null;
      lines.current = [];
      pls.current = [];
    };
  }, []);

  // legend follows the crosshair (or shows the last bar)
  const byTime = React.useMemo(() => new Map(bars.map((b) => [t(b) as number, b])), [bars, t]);
  React.useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const onMove = (p: MouseEventParams) => setLegend(p.time != null ? byTime.get(p.time as number) ?? null : null);
    chart.subscribeCrosshairMove(onMove);
    return () => chart.unsubscribeCrosshairMove(onMove);
  }, [byTime]);

  // bars and volume
  React.useEffect(() => {
    const c = colors.current;
    if (!candles.current || !volume.current || !c) return;
    const prec = precisionFor(bars);
    candles.current.applyOptions({ priceFormat: { type: "price", precision: prec, minMove: 1 / 10 ** prec } });
    const first = bars.length ? bars[0].ns : null;
    const sameView = lastKey.current === viewKey && firstNs.current != null;
    const prepended = sameView && first != null && first < (firstNs.current as number);
    const range = chartRef.current?.timeScale().getVisibleLogicalRange();
    const before = candles.current.data().length;
    candles.current.setData(bars.map((b) => ({ time: t(b), open: b.open, high: b.high, low: b.low, close: b.close })));
    volume.current.setData(bars.map((b) => ({ time: t(b), value: b.volume, color: b.close >= b.open ? c.upVol : c.downVol })));
    // keep the user's view when older bars were added on the left
    if (prepended && range) {
      const shift = bars.length - before;
      chartRef.current?.timeScale().setVisibleLogicalRange({ from: range.from + shift, to: range.to + shift });
    } else if (!sameView) {
      chartRef.current?.timeScale().fitContent();
      if (bars.length > 300) {
        chartRef.current?.timeScale().setVisibleLogicalRange({ from: bars.length - 240, to: bars.length + 4 });
      }
    } else if (follow && range && range.to >= before - 2) {
      chartRef.current?.timeScale().scrollToRealTime();
    }
    firstNs.current = first;
    if (bars.length) lastKey.current = viewKey;
  }, [bars, t, follow, viewKey]);

  // indicators and overlays
  React.useEffect(() => {
    const chart = chartRef.current;
    const c = colors.current;
    if (!chart || !c) return;
    for (const s of lines.current) chart.removeSeries(s);
    lines.current = [];
    const add = (pts: { time: number; value: number }[], color: string, title: string, style = LineStyle.Solid) => {
      const s = chart.addSeries(LineSeries, { color, lineWidth: 1, lineStyle: style, priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerVisible: false, title });
      s.setData(pts.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
      lines.current.push(s);
    };
    const tt = (b: Bar) => t(b) as number;
    let k = 0;
    for (const n of indicators.ma) add(sma(bars, n, tt), c.lines[k++ % c.lines.length], `MA${n}`);
    for (const n of indicators.ema) add(ema(bars, n, tt), c.lines[k++ % c.lines.length], `EMA${n}`);
    if (indicators.bb) {
      const b = bollinger(bars, 20, 2, tt);
      add(b.upper, c.muted, "BB+", LineStyle.Dashed);
      add(b.lower, c.muted, "BB-", LineStyle.Dashed);
    }
    if (indicators.vwap && !daily) add(vwap(bars, tt), c.accent, "VWAP");
    const tone = (x: Overlay["tone"]) => (x === "up" ? c.up : x === "down" ? c.down : x === "accent" ? c.accent : c.muted);
    for (const o of overlays) {
      add(o.points.map((p) => ({ time: t({ ns: p.ns }) as number, value: p.value }))
        .filter((p, i, a) => i === 0 || p.time > a[i - 1].time), tone(o.tone), o.title, LineStyle.Dotted);
    }
  }, [bars, indicators, overlays, daily, t]);

  // trade markers
  React.useEffect(() => {
    const c = colors.current;
    if (!markers.current || !c || !bars.length) return;
    const start = bars[0].ns;
    const list: SeriesMarker<Time>[] = marks
      .filter((m) => m.ns >= start)
      .map((m) => {
        // snap to the bar the trade falls in
        let lo = 0, hi = bars.length - 1;
        while (lo < hi) {
          const mid = (lo + hi + 1) >> 1;
          if (bars[mid].ns <= m.ns) lo = mid; else hi = mid - 1;
        }
        return {
          time: t(bars[lo]), position: m.side === "buy" ? "belowBar" : "aboveBar",
          shape: m.side === "buy" ? "arrowUp" : "arrowDown", color: m.side === "buy" ? c.up : c.down, text: m.text,
        } as SeriesMarker<Time>;
      })
      .sort((a, b) => (a.time as number) - (b.time as number));
    markers.current.setMarkers(list);
  }, [marks, bars, t]);

  // price lines (working orders, average cost)
  React.useEffect(() => {
    const s = candles.current;
    const c = colors.current;
    if (!s || !c) return;
    // keep lines within 10% of the last price in view: autoscale covers them too
    const last = bars.length ? bars[bars.length - 1].close : null;
    const near = last ? priceLines.map((p) => p.price).filter((x) => Math.abs(x - last) / last <= 0.1) : [];
    s.applyOptions({
      autoscaleInfoProvider: (base: () => { priceRange: { minValue: number; maxValue: number } | null } | null) => {
        const r = base();
        if (!r?.priceRange || !near.length) return r;
        return { ...r, priceRange: {
          minValue: Math.min(r.priceRange.minValue, ...near), maxValue: Math.max(r.priceRange.maxValue, ...near) } };
      },
    });
    for (const p of pls.current) s.removePriceLine(p);
    pls.current = priceLines.map((p) => s.createPriceLine({
      price: p.price, title: p.title, lineWidth: 1, axisLabelVisible: true,
      lineStyle: p.dashed ? LineStyle.Dashed : LineStyle.Solid,
      color: p.tone === "up" ? c.up : p.tone === "down" ? c.down : p.tone === "accent" ? c.accent : c.muted,
    }));
  }, [priceLines, bars]);

  const shown = legend ?? bars[bars.length - 1] ?? null;
  const prec = precisionFor(bars);
  const fmt = (v: number) => v.toFixed(prec);
  return (
    <div className={cn("relative h-full w-full", className)}>
      <div ref={host} className="absolute inset-0" />
      {shown && (
        <div className="pointer-events-none absolute left-2 top-1 z-10 flex flex-wrap gap-x-2 font-mono text-[11px] text-muted-foreground">
          <span>O <b className="font-medium text-foreground">{fmt(shown.open)}</b></span>
          <span>H <b className="font-medium text-foreground">{fmt(shown.high)}</b></span>
          <span>L <b className="font-medium text-foreground">{fmt(shown.low)}</b></span>
          <span>C <b className={cn("font-medium", shown.close >= shown.open ? "text-up" : "text-down")}>{fmt(shown.close)}</b></span>
          <span>V <b className="font-medium text-foreground">{shown.volume.toLocaleString(undefined, { maximumFractionDigits: 2 })}</b></span>
        </div>
      )}
      {!bars.length && empty && <div className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">{empty}</div>}
    </div>
  );
}
