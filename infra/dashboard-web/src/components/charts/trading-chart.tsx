"use client";

// The trading chart shared by QFZView and the broker: candles and volume,
// zoom (wheel, pinch) and pan, crosshair legend, moving averages, Bollinger
// bands, VWAP, trade markers, price lines (orders, average price), extra
// line overlays (bid/ask) and, for US stocks, the trading sessions shaded
// behind the candles. Built on TradingView's lightweight-charts.

import * as React from "react";
import {
  CandlestickSeries, createChart, createSeriesMarkers, HistogramSeries, LineSeries, LineStyle,
  type IChartApi, type IPrimitivePaneRenderer, type IPrimitivePaneView, type IPriceLine, type ISeriesApi,
  type ISeriesMarkersPluginApi, type ISeriesPrimitive, type Logical, type LogicalRange, type MouseEventParams, type SeriesAttachedParameter,
  type SeriesMarker, type Time, type UTCTimestamp,
} from "lightweight-charts";

import { useT } from "@/components/locale-provider";
import {
  bollinger, chartTime, dayTime, ema, sessionOf, sessionRuns, sma, vwap, type Bar, type Session, type Zone,
} from "@/lib/bars";
import { cn } from "@/lib/utils";

export interface Indicators { ma: number[]; ema: number[]; bb: boolean; vwap: boolean }
export const DEFAULT_INDICATORS: Indicators = { ma: [20], ema: [], bb: false, vwap: false };

export interface TradeMark { ns: number; side: "buy" | "sell"; text?: string }
export interface PriceLineSpec { price: number; title: string; tone: "up" | "down" | "accent" | "muted"; dashed?: boolean }
export interface Overlay { id: string; title: string; tone: "up" | "down" | "accent" | "muted"; points: { ns: number; value: number }[] }

/** A CSS colour from a design token (canvas needs concrete colours), resolved inside
 * ``within`` so a subtree with its own palette (QFZView's dark background) is honoured. */
function tokenColor(name: string, alpha = 1, within?: HTMLElement | null): string {
  if (typeof document === "undefined") return "#888";
  const el = document.createElement("span");
  el.style.color = `hsl(var(--${name}) / ${alpha})`;
  (within ?? document.body).appendChild(el);
  const c = getComputedStyle(el).color;
  el.remove();
  return c || "#888";
}

function palette(within?: HTMLElement | null) {
  const c = (name: string, alpha = 1) => tokenColor(name, alpha, within);
  return {
    up: c("up"), down: c("down"), upVol: c("up", 0.35), downVol: c("down", 0.35),
    text: c("muted-foreground"), grid: c("border", 0.6), border: c("border"),
    bg: c("card"), accent: c("primary"), muted: c("muted-foreground", 0.8),
    lines: [c("chart-3"), c("chart-1"), c("chart-4"), c("chart-2"), c("chart-5")],
  };
}

export const SESSION_LABEL: Record<Session, [string, string]> = {
  overnight: ["Overnight", "夜盘"], pre: ["Pre-market", "盘前"], regular: ["Regular", "盘中"], post: ["After-hours", "盘后"],
};
/** Shade of each session behind the candles (foreground tint, so it works in both themes); regular is unshaded. */
export const SESSION_SHADE: Record<Session, number> = { overnight: 0.1, pre: 0.06, regular: 0, post: 0.04 };

type Band = { from: number; to: number; session: Session };
type Target = Parameters<IPrimitivePaneRenderer["draw"]>[0];

/** Session bands drawn under the series: one rectangle per run of bars, labelled when wide enough. */
class SessionBands implements ISeriesPrimitive<Time> {
  private chart: SeriesAttachedParameter<Time>["chart"] | null = null;
  private request: (() => void) | null = null;
  private bands: Band[] = [];
  private fills: Partial<Record<Session, string>> = {};
  private labels: Partial<Record<Session, string>> = {};
  private text = "#888";
  private readonly view: IPrimitivePaneView;

  constructor() {
    const draw = (target: Target) => this.draw(target);
    this.view = { zOrder: () => "bottom", renderer: () => ({ draw: () => {}, drawBackground: draw }) };
  }

  attached({ chart, requestUpdate }: SeriesAttachedParameter<Time>) {
    this.chart = chart;
    this.request = requestUpdate;
  }

  detached() {
    this.chart = null;
    this.request = null;
  }

  paneViews() {
    return [this.view];
  }

  set(bands: Band[], fills: Partial<Record<Session, string>>, labels: Partial<Record<Session, string>>, text: string) {
    this.bands = bands;
    this.fills = fills;
    this.labels = labels;
    this.text = text;
    this.request?.();
  }

  private draw(target: Target) {
    const ts = this.chart?.timeScale();
    if (!ts || !this.bands.length) return;
    // the time scale maps whole bar indices only (fractions give 0): edges are centres -/+ half a bar
    const at = (i: number) => ts.logicalToCoordinate(i as Logical);
    const c0 = at(0);
    const c1 = at(1);
    if (c0 == null || c1 == null) return;
    const half = (c1 - c0) / 2;
    target.useBitmapCoordinateSpace(({ context: ctx, bitmapSize, horizontalPixelRatio: hr, verticalPixelRatio: vr }) => {
      ctx.save();
      ctx.font = `${10 * vr}px ui-sans-serif, system-ui, sans-serif`;
      ctx.textBaseline = "top";
      for (const b of this.bands) {
        const fill = this.fills[b.session];
        if (!fill) continue;
        const x1 = at(b.from);
        const x2 = at(b.to);
        if (x1 == null || x2 == null) continue;
        const l = Math.max(0, Math.round((x1 - half) * hr));
        const r = Math.min(bitmapSize.width, Math.round((x2 + half) * hr));
        if (r <= l) continue;
        ctx.fillStyle = fill;
        ctx.fillRect(l, 0, r - l, bitmapSize.height);
        const label = this.labels[b.session];
        if (label && r - l > 44 * hr) {
          ctx.fillStyle = this.text;
          ctx.fillText(label, l + 4 * hr, 20 * vr);
        }
      }
      ctx.restore();
    });
  }
}

/** Index of the first bar at or after ``ns`` when the bars reach it, else ``null``. */
function focusIndex(bars: Bar[], ns: number | null | undefined): number | null {
  if (ns == null || !bars.length || ns < bars[0].ns || ns > bars[bars.length - 1].ns + 86_400e9) return null;
  const i = bars.findIndex((b) => b.ns >= ns);
  return i < 0 ? bars.length - 1 : i;
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
  /** called when the view reaches the last loaded bar (load newer data, after a jump back) */
  onNeedNewer?: () => void;
  /** bring the bar at or after this time (ns) into view, once per value */
  focusNs?: number | null;
  /** keep the latest bar in view as bars are appended (replays) */
  follow?: boolean;
  className?: string;
  empty?: React.ReactNode;
  /** changes when the symbol or interval changes: the view is reset */
  viewKey?: string;
  /** shade the US sessions (overnight, pre-market, after-hours) behind bars of this many minutes */
  sessions?: { minutes: number };
}

export function TradingChart({
  bars, daily = false, zone = "et", indicators = DEFAULT_INDICATORS, marks = [], priceLines = [], overlays = [],
  onNeedOlder, onNeedNewer, focusNs, follow = false, className, empty, viewKey = "", sessions,
}: TradingChartProps) {
  const tr = useT();
  const host = React.useRef<HTMLDivElement>(null);
  const chartRef = React.useRef<IChartApi | null>(null);
  const candles = React.useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volume = React.useRef<ISeriesApi<"Histogram"> | null>(null);
  const lines = React.useRef<ISeriesApi<"Line">[]>([]);
  const markers = React.useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const bands = React.useRef<SessionBands | null>(null);
  const pls = React.useRef<IPriceLine[]>([]);
  const colors = React.useRef<ReturnType<typeof palette> | null>(null);
  const older = React.useRef(onNeedOlder);
  older.current = onNeedOlder;
  const newer = React.useRef(onNeedNewer);
  newer.current = onNeedNewer;
  const count = React.useRef(0);
  count.current = bars.length;
  const focused = React.useRef<number | null>(null);
  // while a jump target is not shown yet, reaching the right edge must not page forward
  const focusPending = React.useRef(false);
  focusPending.current = focusNs != null && focused.current !== focusNs;
  const firstNs = React.useRef<number | null>(null);
  const lastKey = React.useRef<string | null>(null);
  const [legend, setLegend] = React.useState<Bar | null>(null);

  const t = React.useCallback((b: { ns: number; day?: string }) =>
    (daily ? dayTime(b.day ?? new Date(b.ns / 1e6).toISOString().slice(0, 10)) : chartTime(b.ns, zone)) as UTCTimestamp,
  [daily, zone]);

  // create once
  React.useEffect(() => {
    if (!host.current) return;
    const c = palette(host.current);
    colors.current = c;
    const chart = createChart(host.current, {
      autoSize: true,
      layout: { background: { color: c.bg }, textColor: c.text, fontSize: 11, attributionLogo: true },
      grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
      rightPriceScale: { borderColor: c.border, scaleMargins: { top: 0.08, bottom: 0.25 } },
      // appended pages (scrolling right after a jump) must not drag the view along
      timeScale: { borderColor: c.border, timeVisible: true, secondsVisible: false, rightOffset: 4,
                   shiftVisibleRangeOnNewBar: false },
      crosshair: { mode: 0 },
    });
    candles.current = chart.addSeries(CandlestickSeries, {
      upColor: c.up, downColor: c.down, borderUpColor: c.up, borderDownColor: c.down, wickUpColor: c.up, wickDownColor: c.down,
    });
    volume.current = chart.addSeries(HistogramSeries, { priceScaleId: "vol", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    markers.current = createSeriesMarkers(candles.current, []);
    bands.current = new SessionBands();
    candles.current.attachPrimitive(bands.current);
    chartRef.current = chart;

    const onRange = (r: LogicalRange | null) => {
      if (r && r.from < 5 && older.current) older.current();
      if (r && count.current && r.to > count.current - 5 && newer.current && focusPending.current !== true) newer.current();
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
      bands.current = null;
    };
  }, []);

  // session shading (minute bars of US stocks): bar indices are the chart's logical indices
  const sessionMinutes = !daily && sessions ? sessions.minutes : 0;
  React.useEffect(() => {
    if (!bands.current) return;
    if (!sessionMinutes) {
      bands.current.set([], {}, {}, "");
      return;
    }
    const fills: Partial<Record<Session, string>> = {};
    const labels: Partial<Record<Session, string>> = {};
    for (const [k, a] of Object.entries(SESSION_SHADE) as [Session, number][]) {
      if (a > 0) fills[k] = tokenColor("foreground", a, host.current);
      if (k !== "regular") labels[k] = tr(...SESSION_LABEL[k]);
    }
    bands.current.set(sessionRuns(bars, sessionMinutes), fills, labels, tokenColor("muted-foreground", 0.9, host.current));
  }, [bars, sessionMinutes, tr]);

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
      // a new view opens at the jump target when there is one, else on the latest bars
      const fi = focusIndex(bars, focusNs);
      if (fi != null) {
        const width = daily ? 120 : 240;
        focused.current = focusNs ?? null;
        chartRef.current?.timeScale().setVisibleLogicalRange({ from: fi - Math.round(width * 0.15), to: fi + Math.round(width * 0.85) });
      } else {
        chartRef.current?.timeScale().fitContent();
        if (bars.length > 300) {
          chartRef.current?.timeScale().setVisibleLogicalRange({ from: bars.length - 240, to: bars.length + 4 });
        }
      }
    } else if (follow && range && range.to >= before - 2) {
      chartRef.current?.timeScale().scrollToRealTime();
    }
    firstNs.current = first;
    if (bars.length) lastKey.current = viewKey;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bars, t, follow, viewKey]);

  // a jump to a date: show the bars from there on (once per target, after the data arrives)
  React.useEffect(() => {
    if (focusNs == null || focused.current === focusNs || !chartRef.current) return;
    const i = focusIndex(bars, focusNs);
    if (i == null) return;
    focused.current = focusNs;
    const width = daily ? 120 : 240;
    chartRef.current.timeScale().setVisibleLogicalRange({ from: i - Math.round(width * 0.15), to: i + Math.round(width * 0.85) });
  }, [focusNs, bars, daily]);

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
          {sessionMinutes > 0 && <span>{tr(...SESSION_LABEL[sessionOf(shown.ns, sessionMinutes)])}</span>}
        </div>
      )}
      {!bars.length && empty && <div className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">{empty}</div>}
    </div>
  );
}
