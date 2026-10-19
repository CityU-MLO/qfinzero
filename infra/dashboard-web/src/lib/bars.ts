// Bars for the trading charts (QFZView and the broker): one shape for every
// source, aggregation to coarser intervals, indicators, and the time axis.
//
// The chart library works in UTC seconds. US markets are shown in US/Eastern
// time, so their bars are shifted by the Eastern offset of each bar (DST
// included); crypto and FX trade around the clock and are shown in UTC.

export interface Bar {
  /** bar start, ns since the epoch (UTC); daily bars use 00:00 UTC of the day */
  ns: number;
  /** trading day (YYYY-MM-DD) the bar belongs to */
  day: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export type Zone = "et" | "utc";

/** Interval in minutes; 1440 = daily (from daily bars, not aggregated minutes). */
export type Interval = 1 | 5 | 15 | 30 | 60 | 240 | 1440;
export const INTERVALS: { id: Interval; label: string }[] = [
  { id: 1, label: "1m" }, { id: 5, label: "5m" }, { id: 15, label: "15m" }, { id: 30, label: "30m" },
  { id: 60, label: "1h" }, { id: 240, label: "4h" }, { id: 1440, label: "1D" },
];

const NS_MIN = 60_000_000_000;

const etFormatter = typeof Intl !== "undefined"
  ? new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour12: false, year: "numeric", month: "2-digit",
    day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" })
  : null;

/** Offset of US/Eastern from UTC at ``ms`` in seconds (-14400 in summer, -18000 in winter). */
export function etOffsetSec(ms: number): number {
  if (!etFormatter) return -18000;
  const p = Object.fromEntries(etFormatter.formatToParts(new Date(ms)).map((x) => [x.type, x.value]));
  const asUtc = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour % 24, +p.minute, +p.second);
  return Math.round((asUtc - ms) / 1000);
}

/** Chart time (seconds) of a bar: wall-clock time of the zone, encoded as if UTC. */
export function chartTime(ns: number, zone: Zone): number {
  const ms = Math.floor(ns / 1e6);
  const s = Math.floor(ms / 1000);
  return zone === "et" ? s + etOffsetSec(ms) : s;
}

/** Daily bars are keyed by their day at 00:00 "UTC" so every zone shows the same date. */
export function dayTime(day: string): number {
  return Date.UTC(+day.slice(0, 4), +day.slice(5, 7) - 1, +day.slice(8, 10)) / 1000;
}

/** Rows from UPQ minute endpoints (stock, future, crypto, fx, option contract) -> bars. */
export function fromMinuteRows(rows: Record<string, unknown>[]): Bar[] {
  return rows
    .filter((r) => r.window_start != null && r.close != null)
    .map((r) => ({
      ns: Number(r.window_start),
      day: String(r.trade_date ?? ""),
      open: Number(r.open ?? r.close), high: Number(r.high ?? r.close), low: Number(r.low ?? r.close),
      close: Number(r.close), volume: Number(r.volume ?? 0),
    }));
}

/** Rows from UPQ daily endpoints (``date`` or ``trade_date``) -> bars. */
export function fromDailyRows(rows: Record<string, unknown>[], priceKey: "close" | "settle" = "close"): Bar[] {
  return rows
    .filter((r) => (r.date ?? r.trade_date) && (r[priceKey] ?? r.close) != null)
    .map((r) => {
      const day = String(r.date ?? r.trade_date);
      return {
        ns: dayTime(day) * 1e9, day,
        open: Number(r.open ?? r.close), high: Number(r.high ?? r.close), low: Number(r.low ?? r.close),
        close: Number(r[priceKey] ?? r.close), volume: Number(r.volume ?? 0),
      };
    });
}

/** Merge bar lists by start time (later lists win), sorted. */
export function mergeBars(...lists: Bar[][]): Bar[] {
  const m = new Map<number, Bar>();
  for (const l of lists) for (const b of l) m.set(b.ns, b);
  return [...m.values()].sort((a, b) => a.ns - b.ns);
}

/** Aggregate minute bars to ``minutes``-minute bars, aligned to the zone's wall clock. */
export function aggregate(bars: Bar[], minutes: number, zone: Zone): Bar[] {
  if (minutes <= 1) return bars;
  const out: Bar[] = [];
  let cur: Bar | null = null;
  let key = NaN;
  for (const b of bars) {
    const wall = chartTime(b.ns, zone);
    const k = Math.floor(wall / (minutes * 60));
    if (cur && k === key) {
      cur.high = Math.max(cur.high, b.high);
      cur.low = Math.min(cur.low, b.low);
      cur.close = b.close;
      cur.volume += b.volume;
    } else {
      if (cur) out.push(cur);
      // the bucket's start in real UTC ns: shift the wall-clock start back by this bar's offset
      const startWall = k * minutes * 60;
      const ns = (startWall - (wall - Math.floor(b.ns / 1e9))) * 1e9;
      cur = { ...b, ns };
      key = k;
    }
  }
  if (cur) out.push(cur);
  return out;
}

// ── indicators ───────────────────────────────────────────────────────────

export interface Point { time: number; value: number }

export function sma(bars: Bar[], n: number, t: (b: Bar) => number): Point[] {
  const out: Point[] = [];
  let sum = 0;
  for (let i = 0; i < bars.length; i++) {
    sum += bars[i].close;
    if (i >= n) sum -= bars[i - n].close;
    if (i >= n - 1) out.push({ time: t(bars[i]), value: sum / n });
  }
  return out;
}

export function ema(bars: Bar[], n: number, t: (b: Bar) => number): Point[] {
  const out: Point[] = [];
  const k = 2 / (n + 1);
  let e: number | null = null;
  bars.forEach((b, i) => {
    e = e == null ? b.close : b.close * k + e * (1 - k);
    if (i >= n - 1) out.push({ time: t(b), value: e });
  });
  return out;
}

export function bollinger(bars: Bar[], n: number, mult: number, t: (b: Bar) => number): { upper: Point[]; lower: Point[] } {
  const upper: Point[] = [];
  const lower: Point[] = [];
  for (let i = n - 1; i < bars.length; i++) {
    let s = 0;
    for (let j = i - n + 1; j <= i; j++) s += bars[j].close;
    const m = s / n;
    let v = 0;
    for (let j = i - n + 1; j <= i; j++) v += (bars[j].close - m) ** 2;
    const sd = Math.sqrt(v / n);
    upper.push({ time: t(bars[i]), value: m + mult * sd });
    lower.push({ time: t(bars[i]), value: m - mult * sd });
  }
  return { upper, lower };
}

/** Volume-weighted average price, restarting each trading day. */
export function vwap(bars: Bar[], t: (b: Bar) => number): Point[] {
  const out: Point[] = [];
  let day = "";
  let pv = 0;
  let vol = 0;
  for (const b of bars) {
    if (b.day !== day) {
      day = b.day;
      pv = 0;
      vol = 0;
    }
    const typical = (b.high + b.low + b.close) / 3;
    pv += typical * b.volume;
    vol += b.volume;
    if (vol > 0) out.push({ time: t(b), value: pv / vol });
  }
  return out;
}

export const NS_PER_MIN = NS_MIN;
