// Typed client for the PMB broker, proxied through the Next BFF (/api/pmb/* → PMB :19380).

const BASE = "/api/pmb/v1";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!res.ok) {
    const detail =
      (body as { detail?: { message?: string } | string })?.detail ?? body;
    const msg =
      typeof detail === "string"
        ? detail
        : (detail as { message?: string })?.message ?? JSON.stringify(body);
    throw new Error(msg || `request failed (${res.status})`);
  }
  return body as T;
}

// ── Types ────────────────────────────────────────────────────────────────

export interface AccountRow {
  account_id: string;
  market: string;
  status: string;
  initial_cash: number;
  created_at: string;
  current_date: string;
  active_session_id: string | null;
}

export interface AccountSnapshot {
  cash_available: number;
  cash_locked: number;
  loan: number;
  equity: number;
  buying_power: number;
  margin_status: string;
  initial_margin_req: number;
  maintenance_margin_req: number;
  margin_excess: number;
}

export interface Position {
  instrument_id: string;
  qty: number;
  avg_price: number;
  mark_price: number;
  unrealized_pnl: number;
  realized_pnl: number;
}

export interface OpenOrder {
  order_id: string;
  instrument_id: string;
  side: string;
  order_type: string;
  qty: number;
  limit_price: number | null;
  status: string;
}

export interface StockQuote {
  symbol: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Trade {
  [k: string]: unknown;
  ts?: string;
  instrument_id?: string;
  symbol?: string;
  side?: string;
  qty?: number;
  price?: number;
  fee?: number;
}

export interface Clock {
  current_ts: string;
  current_ns: number | null;
  index: number;
  total_bars: number;
  frequency: string;
  start_ts: string;
  end_ts: string;
  status: string;
  is_done: boolean;
}

export interface FullState {
  session_id: string;
  account_id: string;
  clock: Clock;
  account: AccountSnapshot;
  positions: Position[];
  open_orders: OpenOrder[];
  trades: Trade[];
  market: { ts: string; stocks: StockQuote[]; options: unknown[] };
}

// ── Allocate account ───────────────────────────────────────────────────────

export interface AllocateParams {
  initial_cash: number;
  market: string;
  margin_config?: Record<string, number>;
}

export function listAccounts() {
  return req<{ accounts: AccountRow[]; count: number }>("/accounts");
}

export function createAccount(p: AllocateParams) {
  return req<{ account_id: string }>("/accounts", {
    method: "POST",
    body: JSON.stringify(p),
  });
}

// ── Session lifecycle ──────────────────────────────────────────────────────

export function createSession(p: {
  account_id: string;
  start_ts: string;
  end_ts: string;
  stocks: string[];
  frequency?: string;
}) {
  return req<{ session_id: string }>("/sessions", {
    method: "POST",
    body: JSON.stringify({
      account_id: p.account_id,
      frequency: p.frequency ?? "1m",
      start_ts: p.start_ts,
      end_ts: p.end_ts,
      universe: { stocks: p.stocks, options: [] },
    }),
  });
}

export function getState(sessionId: string) {
  return req<FullState>(`/sessions/${sessionId}/state`);
}

export function getTimeline(sessionId: string) {
  return req<{ timeline: string[]; count: number }>(
    `/sessions/${sessionId}/timeline`,
  );
}

export function step(sessionId: string, n: number) {
  return req<{ clock: Clock; events: unknown[] }>(
    `/sessions/${sessionId}/step`,
    { method: "POST", body: JSON.stringify({ step: n }) },
  );
}

export function rewind(sessionId: string, targetTs: string) {
  return req<FullState>(`/sessions/${sessionId}/rewind`, {
    method: "POST",
    body: JSON.stringify({ target_ts: targetTs }),
  });
}

// ── Orders ─────────────────────────────────────────────────────────────────

export function placeOrder(p: {
  session_id: string;
  account_id: string;
  symbol: string;
  side: "BUY" | "SELL";
  qty: number;
  order_type: "MARKET" | "LIMIT";
  limit_price?: number | null;
}) {
  return req<{ ok: boolean; order_id: string; status: string }>("/orders", {
    method: "POST",
    body: JSON.stringify({
      session_id: p.session_id,
      account_id: p.account_id,
      order: {
        instrument: { type: "STOCK", symbol: p.symbol.toUpperCase() },
        side: p.side,
        order_type: p.order_type,
        qty: p.qty,
        limit_price: p.order_type === "LIMIT" ? p.limit_price : null,
      },
    }),
  });
}

export function cancelOrder(orderId: string, sessionId: string, accountId: string) {
  return req<{ ok: boolean }>(`/orders/${orderId}/cancel`, {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, account_id: accountId }),
  });
}

// ── Time helpers ─────────────────────────────────────────────────────────────

/** Format an ISO/UTC bar ts as ET wall-clock (what a US trader sees). */
export function fmtET(ts: string): string {
  if (!ts) return "—";
  const d = new Date(ts.replace(" ", "T"));
  if (isNaN(d.getTime())) return ts;
  return d.toLocaleString("en-US", {
    timeZone: "America/New_York",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function fmtETTime(ts: string): string {
  if (!ts) return "—";
  const d = new Date(ts.replace(" ", "T"));
  if (isNaN(d.getTime())) return ts;
  return d.toLocaleString("en-US", {
    timeZone: "America/New_York",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/** ET hour*60+min for a bar ts, used to find the regular-session open (09:30 ET). */
export function etMinutes(ts: string): number {
  const d = new Date(ts.replace(" ", "T"));
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(d);
  const h = Number(parts.find((p) => p.type === "hour")?.value ?? 0);
  const m = Number(parts.find((p) => p.type === "minute")?.value ?? 0);
  return h * 60 + m;
}

export const money = (n: number | undefined) =>
  n === undefined || n === null
    ? "—"
    : n.toLocaleString("en-US", { style: "currency", currency: "USD" });

export const num = (n: number | undefined, d = 2) =>
  n === undefined || n === null ? "—" : n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
