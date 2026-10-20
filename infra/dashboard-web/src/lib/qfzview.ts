// Market data for QFZView: what kind a symbol is, which data levels its kind
// has in the store, and loaders for bars and quotes from UPQ (via /api/upq).
//
// Symbols follow the coverage map: SPY (stock), /CL (future), X:BTC-USD
// (crypto), C:EUR-USD (FX), O:SPY250117C00500000 (option contract).

import { dayTime, etOffsetSec, fromDailyRows, fromMinuteRows, type Bar, type Interval, type Zone } from "@/lib/bars";

export type Kind = "stock" | "future" | "crypto" | "fx" | "option";

export function kindOf(symbol: string): { kind: Kind; name: string } {
  const s = symbol.trim().toUpperCase();
  if (s.startsWith("/")) return { kind: "future", name: s.slice(1) };
  if (s.startsWith("X:")) return { kind: "crypto", name: s.slice(2) };
  if (s.startsWith("C:")) return { kind: "fx", name: s.slice(2) };
  if (/^O:[A-Z]+\d{6}[CP]\d{8}$/.test(s)) return { kind: "option", name: s };
  return { kind: "stock", name: s };
}

export const zoneOf = (k: Kind): Zone => (k === "crypto" || k === "fx" ? "utc" : "et");

/** Coverage levels (``/api/coverage/extent``) behind each kind's daily, minute and quote data. */
export const LEVELS: Record<Kind, { daily?: string; minute?: string; quotes?: string }> = {
  stock: { daily: "daily", minute: "minute", quotes: "quotes" },
  future: { daily: "futures_daily", minute: "futures_minute", quotes: "futures_quotes" },
  crypto: { daily: "crypto_daily", minute: "crypto_minute" },
  fx: { daily: "fx_daily", minute: "fx_minute", quotes: "fx_quotes" },
  option: { daily: "options_eod", minute: "options_minute", quotes: "options_quotes" },
};

export type Extent = Record<string, { start: string; end: string; days: number } | null>;

async function upq<T>(path: string, params: Record<string, string | number | undefined>): Promise<T> {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== "")
    .map(([k, v]) => [k, String(v)])).toString();
  const r = await fetch(`/api/upq${path}?${qs}`);
  const body = await r.json().catch(() => null);
  if (!r.ok) {
    const b = body as { message?: string; error?: string } | null;
    throw new Error(b?.message ?? b?.error ?? `UPQ ${r.status}`);
  }
  return body as T;
}

type Row = Record<string, unknown>;

/** Calendar days of minute data loaded per page, by interval. A page stays
 * under UPQ's 100,000-row limit (24-hour markets have 1,440 bars a day);
 * scrolling left loads the next page. */
export const MINUTE_SPAN_DAYS: Record<number, number> = { 1: 3, 5: 7, 15: 14, 30: 30, 60: 45, 240: 60 };
export const DAILY_SPAN_DAYS = 365 * 4;

export const isoDay = (d: Date) => d.toISOString().slice(0, 10);
export const addDays = (day: string, n: number) => isoDay(new Date(dayTime(day) * 1000 + n * 86_400_000));

/** One page of bars ending at ``end`` (YYYY-MM-DD, inclusive). ``asOf`` time-locks the query. */
export async function loadBars(symbol: string, interval: Interval, end: string, asOf?: string): Promise<{ bars: Bar[]; start: string }> {
  const { kind, name } = kindOf(symbol);
  const daily = interval === 1440;
  const span = daily ? DAILY_SPAN_DAYS : MINUTE_SPAN_DAYS[interval] ?? 10;
  const start = addDays(end, -span + 1);
  const common = { as_of: asOf };
  if (daily) {
    const rows = kind === "stock" ? await upq<Row[]>("/stock/daily", { tickers: name, start, end, ...common })
      : kind === "future" ? await upq<Row[]>("/future/daily", { tickers: name, start, end, ...common })
        : kind === "crypto" ? await upq<Row[]>("/crypto/daily", { tickers: name, start, end, ...common })
          : kind === "fx" ? await upq<Row[]>("/fx/daily", { tickers: name, start, end, ...common })
            : await upq<Row[]>("/option/ticker_query", { contract: name, start, end, resolution: "day", ...common });
    return { bars: fromDailyRows(rows.map((r) => ({ ...r, date: r.date ?? r.trade_date ?? (r.window_start ? isoDay(new Date(Number(r.window_start) / 1e6)) : undefined) }))), start };
  }
  const s = `${start}T00:00:00`;
  const e = `${addDays(end, 1)}T04:00:00`;   // the ET evening session of `end` ends after midnight UTC
  const lim = { limit: 100000, ...common };
  const rows = kind === "stock" ? await upq<Row[]>("/stock", { tickers: name, start: s, end: e, ...lim })
    : kind === "future" ? await upq<Row[]>("/future", { tickers: name, start: s, end: e, ...lim })
      : kind === "crypto" ? await upq<Row[]>("/crypto", { tickers: name, start: s, end: e, ...lim })
        : kind === "fx" ? await upq<Row[]>("/fx", { tickers: name, start: s, end: e, ...lim })
          : await upq<Row[]>("/option/ticker_query", { contract: name, start: s, end: e, resolution: "minute", ...common });
  return { bars: fromMinuteRows(rows), start };
}

export interface QuotePoint { ns: number; bid: number; ask: number }

/** Bid/ask per kept minute for ``[startNs, endNs]`` (stocks, futures, FX, option contracts). */
export async function loadQuotes(symbol: string, startNs: number, endNs: number, asOf?: string): Promise<QuotePoint[]> {
  const { kind, name } = kindOf(symbol);
  const iso = (ns: number) => new Date(ns / 1e6).toISOString().slice(0, 19);
  const p = { start: iso(startNs), end: iso(endNs + 60e9), limit: 100000, as_of: asOf };
  const rows = kind === "stock" ? await upq<Row[]>("/stock/quote", { tickers: name, ...p })
    : kind === "future" ? await upq<Row[]>("/future/quote", { tickers: name, ...p })
      : kind === "fx" ? await upq<Row[]>("/fx/quote", { tickers: name, ...p })
        : kind === "option" ? await upq<Row[]>("/option/quote", { contract: name, ...p })
          : [];
  return rows.filter((r) => r.bid_price != null && r.ask_price != null)
    .map((r) => ({ ns: Number(r.window_start), bid: Number(r.bid_price), ask: Number(r.ask_price) }));
}

export async function extent(): Promise<{ stores: Extent }> {
  const r = await fetch("/api/coverage/extent");
  if (!r.ok) throw new Error(`coverage ${r.status}`);
  return r.json();
}

export async function suggest(q: string): Promise<{ ticker: string; dollar_volume?: number }[]> {
  const r = await fetch(`/api/coverage/suggest?q=${encodeURIComponent(q)}&limit=12`);
  if (!r.ok) return [];
  return ((await r.json()) as { tickers: { ticker: string; dollar_volume?: number }[] }).tickers;
}

// ── option chains ────────────────────────────────────────────────────────

/** ``O:SPY260821C00766000`` -> its parts, or ``null`` for anything else. */
export function parseOption(symbol: string): { underlying: string; expiry: string; right: "C" | "P"; strike: number } | null {
  const m = /^O:([A-Z]+)\d{0,2}(\d{2})(\d{2})(\d{2})([CP])(\d{8})$/.exec(symbol.trim().toUpperCase());
  if (!m) return null;
  return { underlying: m[1], expiry: `20${m[2]}-${m[3]}-${m[4]}`, right: m[5] as "C" | "P", strike: Number(m[6]) / 1000 };
}

/** UTC ISO time (``YYYY-MM-DDTHH:MM:SSZ``) of an ET wall-clock time. */
export function etToUtcIso(day: string, hm: string): string {
  const wall = Date.UTC(+day.slice(0, 4), +day.slice(5, 7) - 1, +day.slice(8, 10), +hm.slice(0, 2), +hm.slice(3, 5));
  let ms = wall - etOffsetSec(wall) * 1000;
  ms = wall - etOffsetSec(ms) * 1000;          // settle the offset on the real instant (DST edges)
  return new Date(ms).toISOString().slice(0, 19) + "Z";
}

export interface ChainLeg {
  ticker: string;
  last: number | null;
  volume: number | null;
  bid: number | null;
  ask: number | null;
  iv: number | null;
  delta: number | null;
}
export interface ChainRow { strike: number; call?: ChainLeg; put?: ChainLeg }

const numOrNull = (v: unknown) => (v == null || Number.isNaN(Number(v)) ? null : Number(v));

/** Days in ``[start, end]`` with option minute bars for ``underlying`` (coverage map), newest first. */
export async function loadOptionDays(underlying: string, start: string, end: string): Promise<string[]> {
  const r = await fetch(`/api/coverage/matrix?tickers=${encodeURIComponent(underlying)}&start=${start}&end=${end}&events=false`);
  if (!r.ok) return [];
  const m = (await r.json()) as { cells?: Record<string, Record<string, Record<string, number>>> };
  const days = m.cells?.[underlying] ?? {};
  return Object.keys(days).filter((d) => days[d]?.options_minute).sort().reverse();
}

/** The underlying's daily close on (or the last day before) ``day``. */
export async function loadSpot(underlying: string, day: string): Promise<number | null> {
  const rows = await upq<Row[]>("/stock/daily", { tickers: underlying, start: addDays(day, -7), end: day });
  const last = rows.filter((r) => r.close != null).pop();
  return last ? Number(last.close) : null;
}

/** Expiries that traded on ``day``, from the end-of-day chain (calls near the money keep it small). */
export async function loadExpiries(underlying: string, day: string, spot: number | null): Promise<string[]> {
  const rows = await upq<Row[]>("/option/chain_query", {
    underlying, date: day, type: "C",
    strike_min: spot ? Math.floor(spot * 0.85) : undefined, strike_max: spot ? Math.ceil(spot * 1.15) : undefined,
  });
  return [...new Set(rows.map((r) => String(r.expiry)).filter((e) => e >= day))].sort();
}

/** The chain of one expiry as it stood at ``atIso``: last trade, volume, bid/ask, IV and delta, by strike. */
export async function loadChain(underlying: string, atIso: string, expiry: string): Promise<ChainRow[]> {
  const rows = await upq<Row[]>("/option/chain_snapshot", {
    underlying, at: atIso, expiry_min: expiry, expiry_max: expiry, include_greeks: "true",
  });
  const by = new Map<number, ChainRow>();
  for (const r of rows) {
    const strike = Number(r.strike);
    const row = by.get(strike) ?? { strike };
    const leg: ChainLeg = {
      ticker: String(r.ticker), last: numOrNull(r.last), volume: numOrNull(r.volume), bid: numOrNull(r.bid),
      ask: numOrNull(r.ask), iv: numOrNull(r.iv), delta: numOrNull(r.delta),
    };
    if (r.type === "C") row.call = leg; else row.put = leg;
    by.set(strike, row);
  }
  return [...by.values()].sort((a, b) => a.strike - b.strike);
}
