// Market data for QFZView: what kind a symbol is, which data levels its kind
// has in the store, and loaders for bars and quotes from UPQ (via /api/upq).
//
// Symbols follow the coverage map: SPY (stock), /CL (future), X:BTC-USD
// (crypto), C:EUR-USD (FX), O:SPY250117C00500000 (option contract).

import { dayTime, fromDailyRows, fromMinuteRows, type Bar, type Interval, type Zone } from "@/lib/bars";

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
