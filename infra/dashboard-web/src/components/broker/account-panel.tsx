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

import { useT } from "@/components/locale-provider";
import { chart } from "@/lib/chart-theme";
import type { PricePoint } from "./price-chart";

function pnlCls(n: number) {
  return n > 0 ? "text-up" : n < 0 ? "text-down" : "text-foreground";
}

function mult(instrumentId: string) {
  return instrumentId.startsWith("OPTION:") ? 100 : 1;
}

// Display labels for server enum values.
const ENUM_LABEL: Record<string, readonly [string, string]> = {
  BUY: ["BUY", "买入"],
  SELL: ["SELL", "卖出"],
  OK: ["OK", "正常"],
  NORMAL: ["NORMAL", "正常"],
  MARGIN_CALL: ["MARGIN_CALL", "追加保证金"],
  RESTRICTED: ["RESTRICTED", "受限"],
  LIQUIDATION: ["LIQUIDATION", "强制平仓"],
};

function enumLabel(t: (en: string, zh: string) => string, v: string) {
  const l = ENUM_LABEL[v];
  return l ? t(l[0], l[1]) : v;
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
  const t = useT();
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
          <div className="text-lg font-semibold text-foreground">{t("Account", "账户")}</div>
          <div className="font-mono text-xs text-muted-foreground">
            {accountId} · {fmtET(state.clock.current_ts)} ET · {t("bar", "K线")}{" "}
            {state.clock.index + 1}/{state.clock.total_bars}
          </div>
        </div>
        <button
          onClick={onClose}
          className="broker-close flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm text-foreground hover:bg-muted"
        >
          <X className="h-4 w-4" /> {t("Close", "关闭")}
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        {/* Summary tiles */}
        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Tile label={t("Net equity", "净权益")} value={money(a.equity)} />
          <Tile label={t("Day P&L", "当日盈亏")} value={`${dayPnl >= 0 ? "+" : ""}${money(dayPnl)}`} cls={pnlCls(dayPnl)} />
          <Tile label={t("Return", "收益率")} value={`${ret >= 0 ? "+" : ""}${ret.toFixed(2)}%`} cls={pnlCls(ret)} />
          <Tile label={t("Buying power", "购买力")} value={money(a.buying_power)} />
          <Tile label={t("Cash", "现金")} value={money(a.cash_available)} />
          <Tile label={t("Cash locked", "冻结资金")} value={money(a.cash_locked)} />
          <Tile label={t("Unrealized P&L", "未实现盈亏")} value={money(unrealized)} cls={pnlCls(unrealized)} />
          <Tile label={t("Realized P&L", "已实现盈亏")} value={money(realized)} cls={pnlCls(realized)} />
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          {/* Account details */}
          <section>
            <H>{t("Account details", "账户详情")}</H>
            <dl className="broker-panel divide-y divide-border rounded-lg border border-border text-sm">
              <Row k={t("Account ID", "账户 ID")} v={accountId} mono />
              <Row k={t("Session", "会话")} v={state.session_id} mono />
              <Row k={t("Clock", "时钟")} v={`${fmtET(state.clock.current_ts)} ET`} />
              <Row
                k={t("Frequency", "频率")}
                v={state.clock.frequency === "1m" ? t("1-minute", "1 分钟") : t("daily", "日线")}
              />
              <Row
                k={t("Progress", "进度")}
                v={t(
                  `${state.clock.index + 1} / ${state.clock.total_bars} bars${state.clock.is_done ? " (closed)" : ""}`,
                  `${state.clock.index + 1} / ${state.clock.total_bars} 根K线${state.clock.is_done ? "（已收盘）" : ""}`,
                )}
              />
              <Row k={t("Initial equity", "初始权益")} v={money(base)} />
              <Row k={t("Maintenance margin", "维持保证金")} v={money(a.maintenance_margin_req)} />
              <Row k={t("Initial margin", "初始保证金")} v={money(a.initial_margin_req)} />
              <Row k={t("Margin excess", "保证金盈余")} v={money(a.margin_excess)} />
              <Row
                k={t("Margin status", "保证金状态")}
                v={enumLabel(t, a.margin_status)}
                cls={a.margin_status === "NORMAL" || a.margin_status === "OK" ? "text-up" : "text-warning"}
              />
            </dl>
          </section>

          {/* History: equity curve */}
          <section>
            <H>{t("Equity history", "权益曲线")}</H>
            <div className="broker-panel h-48 rounded-lg border border-border p-2">
              {equityHist.length < 2 ? (
                <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                  {t("Equity curve builds as the session plays.", "权益曲线会随会话推进逐步生成。")}
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
                      formatter={(v: number) => [money(v), t("Equity", "权益")]}
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
          <H>
            {t("Holdings", "持仓明细")} ({state.positions.length})
          </H>
          <div className="broker-panel overflow-x-auto rounded-lg border border-border">
            {state.positions.length ? (
              <table className="w-full font-mono text-xs">
                <thead className="bg-card text-muted-foreground">
                  <tr className="text-right">
                    <th className="px-3 py-2 text-left">{t("Instrument", "合约")}</th>
                    <th className="px-3">{t("Qty", "数量")}</th>
                    <th className="px-3">{t("Avg", "均价")}</th>
                    <th className="px-3">{t("Mark", "市价")}</th>
                    <th className="px-3">{t("Mkt value", "市值")}</th>
                    <th className="px-3">{t("Weight", "权重")}</th>
                    <th className="px-3">{t("Unreal.", "未实现")}</th>
                    <th className="px-3">{t("Realized", "已实现")}</th>
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
              <div className="p-6 text-center text-sm text-muted-foreground">{t("No holdings.", "暂无持仓。")}</div>
            )}
          </div>
        </section>

        {/* Trade history */}
        <section className="mt-6">
          <H>
            {t("Trade history", "成交记录")} ({state.trades.length})
          </H>
          <div className="broker-panel overflow-x-auto rounded-lg border border-border">
            {state.trades.length ? (
              <table className="w-full font-mono text-xs">
                <thead className="bg-card text-muted-foreground">
                  <tr className="text-left">
                    <th className="px-3 py-2">{t("Time", "时间")}</th>
                    <th className="px-3">{t("Instrument", "合约")}</th>
                    <th className="px-3">{t("Side", "方向")}</th>
                    <th className="px-3 text-right">{t("Qty", "数量")}</th>
                    <th className="px-3 text-right">{t("Price", "价格")}</th>
                    <th className="px-3 text-right">{t("Fee", "手续费")}</th>
                  </tr>
                </thead>
                <tbody>
                  {state.trades
                    .slice()
                    .reverse()
                    .map((tr, i) => {
                      const s = String(tr.side ?? "");
                      return (
                        <tr key={i} className="border-t border-border">
                          <td className="px-3 py-1.5 text-muted-foreground">{tr.ts ? fmtET(String(tr.ts)) : "—"}</td>
                          <td className="px-3 text-foreground">{String(tr.instrument_id ?? tr.symbol ?? "").replace("STOCK:", "").replace("OPTION:", "")}</td>
                          <td className={`px-3 ${s === "BUY" ? "text-up" : "text-down"}`}>{enumLabel(t, s)}</td>
                          <td className="px-3 text-right">{tr.qty ?? "—"}</td>
                          <td className="px-3 text-right">{tr.price != null ? num(Number(tr.price)) : "—"}</td>
                          <td className="px-3 text-right text-muted-foreground">{tr.fee != null ? num(Number(tr.fee)) : "—"}</td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            ) : (
              <div className="p-6 text-center text-sm text-muted-foreground">{t("No fills yet.", "暂无成交。")}</div>
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
