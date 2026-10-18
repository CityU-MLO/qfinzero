"use client";

import { X } from "lucide-react";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { fmtET, fmtETTime, money, num, type FullState } from "./api";

import { chart } from "@/lib/chart-theme";
import type { PricePoint } from "./price-chart";

function pnlCls(n: number) {
  return n > 0 ? "text-up" : n < 0 ? "text-down" : "text-foreground";
}

function mult(instrumentId: string) {
  return instrumentId.startsWith("OPTION:") ? 100 : 1;
}

export function AccountPanel({
  accountId,
  state,
  equityHist,
  initialEquity,
  onClose,
}: {
  accountId: string;
  state: FullState;
  equityHist: PricePoint[];
  initialEquity: number | null;
  onClose: () => void;
}) {
  const a = state.account;
  const base = initialEquity ?? a.equity;
  const dayPnl = a.equity - base;
  const ret = base ? (dayPnl / base) * 100 : 0;
  const eqUp = equityHist.length < 2 || equityHist[equityHist.length - 1].price >= equityHist[0].price;
  const unrealized = state.positions.reduce((s, p) => s + p.unrealized_pnl, 0);
  const realized = state.positions.reduce((s, p) => s + p.realized_pnl, 0);

  return (
    <div className="absolute inset-0 z-20 flex flex-col bg-card">
      {/* Title bar */}
      <div className="broker-titlebar flex items-center justify-between border-b border-border px-5 py-3">
        <div>
          <div className="text-lg font-semibold text-foreground">Account</div>
          <div className="font-mono text-xs text-muted-foreground">
            {accountId} · {fmtET(state.clock.current_ts)} ET · bar{" "}
            {state.clock.index + 1}/{state.clock.total_bars}
          </div>
        </div>
        <button
          onClick={onClose}
          className="broker-close flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm text-foreground hover:bg-muted"
        >
          <X className="h-4 w-4" /> Close
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        {/* Summary tiles */}
        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Tile label="Net equity" value={money(a.equity)} />
          <Tile label="Day P&L" value={`${dayPnl >= 0 ? "+" : ""}${money(dayPnl)}`} cls={pnlCls(dayPnl)} />
          <Tile label="Return" value={`${ret >= 0 ? "+" : ""}${ret.toFixed(2)}%`} cls={pnlCls(ret)} />
          <Tile label="Buying power" value={money(a.buying_power)} />
          <Tile label="Cash" value={money(a.cash_available)} />
          <Tile label="Cash locked" value={money(a.cash_locked)} />
          <Tile label="Unrealized P&L" value={money(unrealized)} cls={pnlCls(unrealized)} />
          <Tile label="Realized P&L" value={money(realized)} cls={pnlCls(realized)} />
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          {/* Account details */}
          <section>
            <H>Account details</H>
            <dl className="broker-panel divide-y divide-border rounded-lg border border-border text-sm">
              <Row k="Account ID" v={accountId} mono />
              <Row k="Session" v={state.session_id} mono />
              <Row k="Clock" v={`${fmtET(state.clock.current_ts)} ET`} />
              <Row k="Frequency" v={state.clock.frequency === "1m" ? "1-minute" : "daily"} />
              <Row
                k="Progress"
                v={`${state.clock.index + 1} / ${state.clock.total_bars} bars${state.clock.is_done ? " (closed)" : ""}`}
              />
              <Row k="Initial equity" v={money(base)} />
              <Row k="Maintenance margin" v={money(a.maintenance_margin_req)} />
              <Row k="Initial margin" v={money(a.initial_margin_req)} />
              <Row k="Margin excess" v={money(a.margin_excess)} />
              <Row
                k="Margin status"
                v={a.margin_status}
                cls={a.margin_status === "OK" ? "text-up" : "text-warning"}
              />
            </dl>
          </section>

          {/* History: equity curve */}
          <section>
            <H>Equity history</H>
            <div className="broker-panel h-48 rounded-lg border border-border p-2">
              {equityHist.length < 2 ? (
                <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                  Equity curve builds as the session plays.
                </div>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={equityHist} margin={{ top: 6, right: 6, bottom: 0, left: 0 }}>
                    <defs>
                      <linearGradient id="eqfill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={eqUp ? chart.up : chart.down} stopOpacity={0.18} />
                        <stop offset="100%" stopColor={eqUp ? chart.up : chart.down} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <XAxis dataKey="ts" tickFormatter={fmtETTime} tick={chart.tick} minTickGap={40} tickLine={false} axisLine={{ stroke: chart.grid }} />
                    <YAxis domain={["auto", "auto"]} orientation="right" width={64} tick={chart.tick} tickFormatter={(v) => money(v)} tickLine={false} axisLine={false} />
                    <Tooltip
                      contentStyle={chart.tooltip.contentStyle}
                      labelFormatter={(l) => fmtET(String(l))}
                      formatter={(v: number) => [money(v), "Equity"]}
                    />
                    <Area type="monotone" dataKey="price" stroke={eqUp ? chart.up : chart.down} strokeWidth={1.5} fill="url(#eqfill)" isAnimationActive={false} dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>
          </section>
        </div>

        {/* Holdings */}
        <section className="mt-6">
          <H>Holdings ({state.positions.length})</H>
          <div className="broker-panel overflow-x-auto rounded-lg border border-border">
            {state.positions.length ? (
              <table className="w-full font-mono text-xs">
                <thead className="bg-card text-muted-foreground">
                  <tr className="text-right">
                    <th className="px-3 py-2 text-left">Instrument</th>
                    <th className="px-3">Qty</th>
                    <th className="px-3">Avg</th>
                    <th className="px-3">Mark</th>
                    <th className="px-3">Mkt value</th>
                    <th className="px-3">Weight</th>
                    <th className="px-3">Unreal.</th>
                    <th className="px-3">Realized</th>
                  </tr>
                </thead>
                <tbody>
                  {state.positions.map((p) => {
                    const mv = p.qty * p.mark_price * mult(p.instrument_id);
                    const w = a.equity ? (mv / a.equity) * 100 : 0;
                    return (
                      <tr key={p.instrument_id} className="border-t border-border text-right">
                        <td className="px-3 py-1.5 text-left text-foreground">{p.instrument_id.replace("STOCK:", "").replace("OPTION:", "")}</td>
                        <td className="px-3">{p.qty}</td>
                        <td className="px-3">{num(p.avg_price)}</td>
                        <td className="px-3">{num(p.mark_price)}</td>
                        <td className="px-3">{money(mv)}</td>
                        <td className="px-3 text-muted-foreground">{w.toFixed(1)}%</td>
                        <td className={`px-3 ${pnlCls(p.unrealized_pnl)}`}>{p.unrealized_pnl >= 0 ? "+" : ""}{num(p.unrealized_pnl)}</td>
                        <td className={`px-3 ${pnlCls(p.realized_pnl)}`}>{num(p.realized_pnl)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <div className="p-6 text-center text-sm text-muted-foreground">No holdings.</div>
            )}
          </div>
        </section>

        {/* Trade history */}
        <section className="mt-6">
          <H>Trade history ({state.trades.length})</H>
          <div className="broker-panel overflow-x-auto rounded-lg border border-border">
            {state.trades.length ? (
              <table className="w-full font-mono text-xs">
                <thead className="bg-card text-muted-foreground">
                  <tr className="text-left">
                    <th className="px-3 py-2">Time</th>
                    <th className="px-3">Instrument</th>
                    <th className="px-3">Side</th>
                    <th className="px-3 text-right">Qty</th>
                    <th className="px-3 text-right">Price</th>
                    <th className="px-3 text-right">Fee</th>
                  </tr>
                </thead>
                <tbody>
                  {state.trades
                    .slice()
                    .reverse()
                    .map((t, i) => {
                      const s = String(t.side ?? "");
                      return (
                        <tr key={i} className="border-t border-border">
                          <td className="px-3 py-1.5 text-muted-foreground">{t.ts ? fmtET(String(t.ts)) : "—"}</td>
                          <td className="px-3 text-foreground">{String(t.instrument_id ?? t.symbol ?? "").replace("STOCK:", "").replace("OPTION:", "")}</td>
                          <td className={`px-3 ${s === "BUY" ? "text-up" : "text-down"}`}>{s}</td>
                          <td className="px-3 text-right">{t.qty ?? "—"}</td>
                          <td className="px-3 text-right">{t.price != null ? num(Number(t.price)) : "—"}</td>
                          <td className="px-3 text-right text-muted-foreground">{t.fee != null ? num(Number(t.fee)) : "—"}</td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            ) : (
              <div className="p-6 text-center text-sm text-muted-foreground">No fills yet.</div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function Tile({ label, value, cls }: { label: string; value: string; cls?: string }) {
  return (
    <div className="broker-panel rounded-lg border border-border px-4 py-3">
      <div className="text-[10px] text-muted-foreground">{label}</div>
      <div className={`mt-0.5 font-mono text-lg font-semibold ${cls ?? "text-foreground"}`}>{value}</div>
    </div>
  );
}

function H({ children }: { children: React.ReactNode }) {
  return <div className="mb-2 text-xs font-semibold text-muted-foreground">{children}</div>;
}

function Row({ k, v, mono, cls }: { k: string; v: string; mono?: boolean; cls?: string }) {
  return (
    <div className="flex items-center justify-between px-4 py-2">
      <span className="text-muted-foreground">{k}</span>
      <span className={`${mono ? "font-mono" : ""} ${cls ?? "text-foreground"}`}>{v}</span>
    </div>
  );
}
