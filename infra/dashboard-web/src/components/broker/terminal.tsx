"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  LogOut,
  TrendingUp,
  TrendingDown,
  X,
  Wallet2,
  CandlestickChart,
  ListTree,
  LineChart as LineChartIcon,
  Plus,
  Trash2,
  Ban,
} from "lucide-react";

import {
  getState,
  getTimeline,
  step,
  rewind,
  placeOrder,
  placeOptionOrder,
  cancelOrder,
  addStocks,
  etMinutes,
  money,
  num,
  fmtET,
  type FullState,
  type Position,
} from "./api";
import { PriceChart, type PricePoint } from "./price-chart";
import { CandleChart, type Candle } from "./candle-chart";
import { ClockBar } from "./clock-bar";
import { OptionChain } from "./option-chain";
import { AccountPanel } from "./account-panel";

const MARKET_OPEN_ET = 9 * 60 + 30; // 09:30 ET

type Blotter = "positions" | "orders" | "trades";

function pnlCls(n: number) {
  return n > 0 ? "text-up" : n < 0 ? "text-down" : "text-foreground";
}

export function Terminal({
  sessionId,
  accountId,
  watchlist,
  onExit,
}: {
  sessionId: string;
  accountId: string;
  watchlist: string[];
  onExit: () => void;
}) {
  const [state, setState] = useState<FullState | null>(null);
  const [timeline, setTimeline] = useState<string[]>([]);
  const [wl, setWl] = useState<string[]>(watchlist);
  const [selected, setSelected] = useState(watchlist[0] ?? "AAPL");
  const [newSym, setNewSym] = useState("");
  const [addingSym, setAddingSym] = useState(false);
  const [chartKind, setChartKind] = useState<"candles" | "line">("candles");
  const [priceHist, setPriceHist] = useState<Record<string, PricePoint[]>>({});
  const [ohlcHist, setOhlcHist] = useState<Record<string, Candle[]>>({});
  const [started, setStarted] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(5);
  const [scrubbing, setScrubbing] = useState(false);
  const [tab, setTab] = useState<Blotter>("positions");
  const [err, setErr] = useState<string | null>(null);
  const [initialEquity, setInitialEquity] = useState<number | null>(null);
  const [equityHist, setEquityHist] = useState<PricePoint[]>([]);
  const [centerView, setCenterView] = useState<"chart" | "options">("chart");
  const [showAccount, setShowAccount] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  // Order ticket
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [qty, setQty] = useState(100);
  const [orderType, setOrderType] = useState<"MARKET" | "LIMIT">("MARKET");
  const [limit, setLimit] = useState<number | "">("");
  const busy2Ref = useRef(false);

  const stateRef = useRef<FullState | null>(null);
  const playingRef = useRef(false);
  const speedRef = useRef(speed);
  const busyRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scrubTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const apply = useCallback((s: FullState, accumulate: boolean) => {
    stateRef.current = s;
    setState(s);
    if (accumulate) {
      const curTs = s.market.ts;
      setEquityHist((prev) => {
        const arr = prev.filter((p) => p.ts <= curTs);
        if (!arr.length || arr[arr.length - 1].ts !== curTs)
          arr.push({ ts: curTs, price: s.account.equity });
        else arr[arr.length - 1] = { ts: curTs, price: s.account.equity };
        return arr;
      });
      setPriceHist((prev) => {
        const next = { ...prev };
        for (const q of s.market.stocks) {
          const arr = (next[q.symbol] ?? []).filter((p) => p.ts <= curTs);
          if (!arr.length || arr[arr.length - 1].ts !== curTs)
            arr.push({ ts: curTs, price: q.close });
          else arr[arr.length - 1] = { ts: curTs, price: q.close };
          next[q.symbol] = arr;
        }
        return next;
      });
      setOhlcHist((prev) => {
        const next = { ...prev };
        for (const q of s.market.stocks) {
          const arr = (next[q.symbol] ?? []).filter((p) => p.ts <= curTs);
          const bar: Candle = { ts: curTs, o: q.open, h: q.high, l: q.low, c: q.close, v: q.volume };
          if (!arr.length || arr[arr.length - 1].ts !== curTs) arr.push(bar);
          else arr[arr.length - 1] = bar;
          next[q.symbol] = arr;
        }
        return next;
      });
    }
  }, []);

  // initial load
  useEffect(() => {
    (async () => {
      try {
        const [tl, s] = await Promise.all([getTimeline(sessionId), getState(sessionId)]);
        setTimeline(tl.timeline);
        apply(s, false);
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const doStep = useCallback(
    async (n: number) => {
      if (busyRef.current) return;
      busyRef.current = true;
      try {
        await step(sessionId, n);
        const s = await getState(sessionId);
        apply(s, true);
        if (initialEquity === null) setInitialEquity(s.account.equity);
        if (s.clock.is_done) {
          playingRef.current = false;
          setPlaying(false);
        }
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      } finally {
        busyRef.current = false;
      }
    },
    [sessionId, apply, initialEquity],
  );

  const loop = useCallback(() => {
    if (!playingRef.current) return;
    const clk = stateRef.current?.clock;
    if (!clk || clk.is_done) {
      playingRef.current = false;
      setPlaying(false);
      return;
    }
    const sp = speedRef.current;
    const bars = sp <= 8 ? 1 : Math.ceil(sp / 8);
    const interval = sp <= 8 ? 1000 / sp : 1000 / 8;
    doStep(bars).then(() => {
      if (playingRef.current) timerRef.current = setTimeout(loop, interval);
    });
  }, [doStep]);

  const play = useCallback(() => {
    if (playingRef.current) return;
    playingRef.current = true;
    setPlaying(true);
    loop();
  }, [loop]);

  const pause = useCallback(() => {
    playingRef.current = false;
    setPlaying(false);
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  // seek helper — rewind endpoint positions the clock and undoes later actions
  const seek = useCallback(
    async (index: number) => {
      const ts = timeline[index];
      if (!ts) return;
      setScrubbing(true);
      try {
        const s = await rewind(sessionId, ts);
        apply(s, true);
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      } finally {
        setScrubbing(false);
      }
    },
    [sessionId, timeline, apply],
  );

  const onStart = useCallback(async () => {
    // Open at the regular-session open (09:30 ET), then let time flow.
    let openIdx = timeline.findIndex((ts) => etMinutes(ts) >= MARKET_OPEN_ET);
    if (openIdx < 0) openIdx = 0;
    setStarted(true);
    await seek(openIdx);
    play();
  }, [timeline, seek, play]);

  const onScrub = useCallback(
    (index: number) => {
      pause();
      // reflect immediately, debounce the (expensive) rewind
      setState((s) => (s ? { ...s, clock: { ...s.clock, index } } : s));
      if (scrubTimer.current) clearTimeout(scrubTimer.current);
      scrubTimer.current = setTimeout(() => seek(index), 120);
    },
    [pause, seek],
  );

  const submitOrder = useCallback(async () => {
    setErr(null);
    try {
      await placeOrder({
        session_id: sessionId,
        account_id: accountId,
        symbol: selected,
        side,
        qty,
        order_type: orderType,
        limit_price: orderType === "LIMIT" ? Number(limit) : null,
      });
      const s = await getState(sessionId);
      apply(s, true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [sessionId, accountId, selected, side, qty, orderType, limit, apply]);

  const tradeContract = useCallback(
    async (contract: string, oside: "BUY" | "SELL") => {
      setErr(null);
      try {
        await placeOptionOrder({
          session_id: sessionId,
          account_id: accountId,
          contract,
          side: oside,
          qty: Math.max(1, Math.round(qty / 100) || 1),
          order_type: "MARKET",
        });
        const s = await getState(sessionId);
        apply(s, true);
        setToast(`${oside} ${contract} submitted`);
        setTimeout(() => setToast(null), 2500);
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      }
    },
    [sessionId, accountId, qty, apply],
  );

  const addSymbol = useCallback(async () => {
    const sym = newSym.trim().toUpperCase();
    if (!sym) return;
    if (wl.includes(sym)) {
      setSelected(sym);
      setNewSym("");
      return;
    }
    setAddingSym(true);
    setErr(null);
    try {
      const r = await addStocks(sessionId, [sym]);
      if (r.loaded === 0) {
        setErr(`No market data for ${sym} on this trading day.`);
      } else {
        setWl((w) => [...w, sym]);
        setSelected(sym);
        const s = await getState(sessionId);
        apply(s, true);
        setNewSym("");
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setAddingSym(false);
    }
  }, [newSym, wl, sessionId, apply]);

  const removeSymbol = useCallback((sym: string) => {
    setWl((w) => {
      const nw = w.filter((x) => x !== sym);
      setSelected((sel) => (sel === sym ? nw[0] ?? sel : sel));
      return nw.length ? nw : w; // keep at least one
    });
  }, []);

  const flatten = useCallback(
    async (p: Position) => {
      if (busy2Ref.current) return;
      busy2Ref.current = true;
      setErr(null);
      try {
        const oside = (p.qty > 0 ? "SELL" : "BUY") as "BUY" | "SELL";
        const q = Math.abs(p.qty);
        if (p.instrument_id.startsWith("OPTION:")) {
          await placeOptionOrder({
            session_id: sessionId,
            account_id: accountId,
            contract: p.instrument_id.slice("OPTION:".length),
            side: oside,
            qty: q,
            order_type: "MARKET",
          });
        } else {
          await placeOrder({
            session_id: sessionId,
            account_id: accountId,
            symbol: p.instrument_id.slice("STOCK:".length),
            side: oside,
            qty: q,
            order_type: "MARKET",
          });
        }
        const s = await getState(sessionId);
        apply(s, true);
        setToast(`Flatten ${p.instrument_id.replace(/^(STOCK|OPTION):/, "")} submitted`);
        setTimeout(() => setToast(null), 2500);
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      } finally {
        busy2Ref.current = false;
      }
    },
    [sessionId, accountId, apply],
  );

  const closeAll = useCallback(async () => {
    for (const p of stateRef.current?.positions ?? []) await flatten(p);
  }, [flatten]);

  const cancelAll = useCallback(async () => {
    for (const o of stateRef.current?.open_orders ?? []) {
      try {
        await cancelOrder(o.order_id, sessionId, accountId);
      } catch {
        /* ignore */
      }
    }
    const s = await getState(sessionId);
    apply(s, true);
  }, [sessionId, accountId, apply]);

  const doCancel = useCallback(
    async (orderId: string) => {
      try {
        await cancelOrder(orderId, sessionId, accountId);
        const s = await getState(sessionId);
        apply(s, true);
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      }
    },
    [sessionId, accountId, apply],
  );

  useEffect(() => {
    speedRef.current = speed;
  }, [speed]);

  // ── derived ──
  const quotes = state?.market.stocks ?? [];
  const quoteFor = (sym: string) => quotes.find((q) => q.symbol === sym);
  const sel = quoteFor(selected);
  const selHist = priceHist[selected] ?? [];
  const selUp = selHist.length < 2 || selHist[selHist.length - 1].price >= selHist[0].price;

  const acct = state?.account;
  const dayPnl = acct && initialEquity !== null ? acct.equity - initialEquity : 0;
  const selCandles = ohlcHist[selected] ?? [];
  const changePct = (sym: string): number | null => {
    const h = ohlcHist[sym] ?? [];
    if (!h.length) return null;
    const open = h[0].o;
    return open ? ((h[h.length - 1].c - open) / open) * 100 : null;
  };
  const estCost = sel ? qty * sel.close : 0;
  const bpAfter = acct ? acct.buying_power - (side === "BUY" ? estCost : 0) : 0;

  return (
    <div className="broker-root relative flex h-full flex-col bg-card text-foreground">
      {/* Header */}
      <div className="broker-titlebar flex items-center justify-between border-b border-border px-5 py-3">
        <div className="flex items-center gap-4">
          <div className="text-sm font-semibold text-foreground">Session</div>
          <div className="hidden font-mono text-xs text-muted-foreground sm:block">
            acct {accountId} · {state ? fmtET(state.clock.current_ts) : "—"} ET
          </div>
        </div>
        <div className="flex items-center gap-5">
          <Stat label="Equity" value={money(acct?.equity)} />
          <Stat
            label="Day P&L"
            value={`${dayPnl >= 0 ? "+" : ""}${money(dayPnl)}`}
            cls={pnlCls(dayPnl)}
          />
          <Stat label="Buying power" value={money(acct?.buying_power)} />
          <button
            onClick={() => setShowAccount(true)}
            className="broker-btn flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm text-foreground hover:bg-muted"
          >
            <Wallet2 className="h-4 w-4" /> Account
          </button>
          <button
            onClick={onExit}
            className="broker-btn flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm text-foreground hover:bg-muted"
          >
            <LogOut className="h-4 w-4" /> Exit
          </button>
        </div>
      </div>

      {err && (
        <div className="flex items-center justify-between border-b border-destructive/30 bg-destructive/5 px-5 py-1.5 text-sm text-destructive">
          {err}
          <button onClick={() => setErr(null)}>
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Body */}
      <div className="flex min-h-0 flex-1">
        {/* Watchlist */}
        <div className="broker-panel flex w-60 shrink-0 flex-col border-r border-border">
          <div className="px-3 py-2 text-xs font-semibold text-muted-foreground">
            Watchlist
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {wl.map((sym) => {
              const q = quoteFor(sym);
              const chg = changePct(sym);
              const up = chg == null ? true : chg >= 0;
              return (
                <div
                  key={sym}
                  className={`group flex w-full items-center justify-between px-3 py-2.5 transition ${
                    selected === sym ? "bg-muted" : "hover:bg-muted"
                  }`}
                >
                  <button onClick={() => setSelected(sym)} className="flex flex-1 flex-col items-start text-left">
                    <span className="font-semibold text-foreground">{sym}</span>
                    {chg != null && (
                      <span className={`font-mono text-[11px] ${up ? "text-up" : "text-down"}`}>
                        {chg >= 0 ? "+" : ""}
                        {chg.toFixed(2)}%
                      </span>
                    )}
                  </button>
                  <span className="flex items-center gap-1.5 font-mono text-sm">
                    <span className={q ? (up ? "text-up" : "text-down") : "text-muted-foreground"}>
                      {q ? num(q.close) : "—"}
                    </span>
                    {q && (up ? <TrendingUp className="h-3 w-3 text-up" /> : <TrendingDown className="h-3 w-3 text-down" />)}
                    <button
                      onClick={() => removeSymbol(sym)}
                      title="Remove from watchlist"
                      className="broker-btn opacity-0 transition group-hover:opacity-100 text-muted-foreground hover:text-down"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </span>
                </div>
              );
            })}
          </div>
          {/* Add symbol */}
          <div className="flex items-center gap-1 border-t border-border p-2">
            <input
              value={newSym}
              onChange={(e) => setNewSym(e.target.value.toUpperCase())}
              onKeyDown={(e) => e.key === "Enter" && addSymbol()}
              placeholder="Add symbol…"
              className="w-full rounded-md border border-input bg-card px-2 py-1.5 text-sm text-foreground outline-none focus:border-ring focus:ring-2 focus:ring-ring/20"
            />
            <button
              onClick={addSymbol}
              disabled={addingSym || !newSym.trim()}
              className="broker-btn flex items-center justify-center rounded-md bg-up px-2 py-1.5 text-white disabled:opacity-40"
              title="Add to watchlist"
            >
              <Plus className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Center: chart + blotter */}
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center justify-between px-5 pt-3">
            <div className="flex items-baseline gap-3">
              <span className="text-2xl font-semibold text-foreground">{selected}</span>
              <span className={`font-mono text-xl ${sel ? (selUp ? "text-up" : "text-down") : "text-muted-foreground"}`}>
                {sel ? num(sel.close) : "—"}
              </span>
              {(() => {
                const c = changePct(selected);
                return c == null ? null : (
                  <span className={`font-mono text-sm font-semibold ${c >= 0 ? "text-up" : "text-down"}`}>
                    {c >= 0 ? "+" : ""}
                    {c.toFixed(2)}%
                  </span>
                );
              })()}
              {sel && (
                <span className="font-mono text-xs text-muted-foreground">
                  O {num(sel.open)} · H {num(sel.high)} · L {num(sel.low)} · Vol{" "}
                  {sel.volume.toLocaleString()}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              {centerView === "chart" && (
                <div className="flex overflow-hidden rounded-lg border border-border text-xs">
                  {([["candles", CandlestickChart], ["line", LineChartIcon]] as const).map(([id, Icon]) => (
                    <button
                      key={id}
                      onClick={() => setChartKind(id)}
                      className={`broker-btn flex items-center px-2.5 py-1.5 ${
                        chartKind === id ? "bg-muted text-foreground" : "bg-card text-muted-foreground"
                      }`}
                      title={id === "candles" ? "Candlesticks" : "Line"}
                    >
                      <Icon className="h-3.5 w-3.5" />
                    </button>
                  ))}
                </div>
              )}
              <div className="flex overflow-hidden rounded-lg border border-border text-xs">
                {([["chart", "Chart", CandlestickChart], ["options", "Option chain", ListTree]] as const).map(
                  ([id, label, Icon]) => (
                    <button
                      key={id}
                      onClick={() => setCenterView(id)}
                      className={`broker-btn flex items-center gap-1.5 px-3 py-1.5 font-semibold ${
                        centerView === id ? "bg-muted text-foreground" : "bg-card text-muted-foreground"
                      }`}
                    >
                      <Icon className="h-3.5 w-3.5" /> {label}
                    </button>
                  ),
                )}
              </div>
            </div>
          </div>
          <div className="min-h-0 flex-1 px-3 pb-2 pt-1">
            {centerView === "chart" ? (
              chartKind === "candles" ? (
                <CandleChart symbol={selected} data={selCandles} />
              ) : (
                <PriceChart symbol={selected} data={selHist} up={selUp} />
              )
            ) : (
              <OptionChain
                sessionId={sessionId}
                underlying={selected}
                clockIndex={state?.clock.index ?? -1}
                onTrade={tradeContract}
              />
            )}
          </div>

          {/* Blotter */}
          <div className="broker-panel h-56 shrink-0 border-t border-border">
            <div className="flex items-center justify-between px-4 pt-2">
              <div className="flex gap-1">
                {(["positions", "orders", "trades"] as Blotter[]).map((t) => (
                  <button
                    key={t}
                    onClick={() => setTab(t)}
                    className={`broker-btn rounded-t-md px-3 py-1.5 text-xs font-semibold capitalize ${
                      tab === t ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {t}
                    {t === "positions" && state?.positions.length ? ` (${state.positions.length})` : ""}
                    {t === "orders" && state?.open_orders.length ? ` (${state.open_orders.length})` : ""}
                  </button>
                ))}
              </div>
              {tab === "positions" && !!state?.positions.length && (
                <button
                  onClick={closeAll}
                  className="broker-btn flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] text-foreground hover:bg-muted"
                >
                  <X className="h-3 w-3" /> Close all
                </button>
              )}
              {tab === "orders" && !!state?.open_orders.length && (
                <button
                  onClick={cancelAll}
                  className="broker-btn flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] text-foreground hover:bg-muted"
                >
                  <Ban className="h-3 w-3" /> Cancel all
                </button>
              )}
            </div>
            <div className="h-[calc(100%-2.25rem)] overflow-y-auto px-4 py-2 font-mono text-xs">
              {tab === "positions" && (
                <PositionsTable positions={state?.positions ?? []} onFlatten={flatten} />
              )}
              {tab === "orders" && (
                <OrdersTable orders={state?.open_orders ?? []} onCancel={doCancel} />
              )}
              {tab === "trades" && <TradesTable trades={state?.trades ?? []} />}
            </div>
          </div>
        </div>

        {/* Order ticket + account */}
        <div className="w-72 shrink-0 overflow-y-auto border-l border-border p-4">
          <div className="mb-3 text-xs font-semibold text-muted-foreground">
            Order ticket
          </div>
          <div className="mb-3 grid grid-cols-2 gap-2">
            {(["BUY", "SELL"] as const).map((s) => (
              <button
                key={s}
                onClick={() => setSide(s)}
                className={`rounded-lg py-2 text-sm font-semibold transition ${
                  side === s
                    ? s === "BUY"
                      ? "bg-up text-white"
                      : "bg-down text-white"
                    : "bg-muted text-muted-foreground hover:bg-accent"
                }`}
              >
                {s}
              </button>
            ))}
          </div>

          <TicketField label="Symbol">
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              className="w-full rounded-md border border-input bg-card px-3 py-2 text-sm text-foreground outline-none focus:border-ring focus:ring-2 focus:ring-ring/20"
            >
              {wl.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </TicketField>

          <TicketField label="Quantity (shares)">
            <input
              type="number"
              min={1}
              value={qty}
              onChange={(e) => setQty(Math.max(1, Number(e.target.value)))}
              className="w-full rounded-md border border-input bg-card px-3 py-2 text-sm text-foreground outline-none focus:border-ring focus:ring-2 focus:ring-ring/20"
            />
          </TicketField>

          <TicketField label="Type">
            <div className="grid grid-cols-2 gap-2">
              {(["MARKET", "LIMIT"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setOrderType(t)}
                  className={`rounded-lg py-1.5 text-xs font-semibold ${
                    orderType === t ? "bg-secondary text-foreground" : "bg-muted text-muted-foreground"
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
          </TicketField>

          {orderType === "LIMIT" && (
            <TicketField label="Limit price">
              <input
                type="number"
                step="0.01"
                value={limit}
                onChange={(e) => setLimit(e.target.value === "" ? "" : Number(e.target.value))}
                placeholder={sel ? num(sel.close) : "0.00"}
                className="w-full rounded-md border border-input bg-card px-3 py-2 text-sm text-foreground outline-none focus:border-ring focus:ring-2 focus:ring-ring/20"
              />
            </TicketField>
          )}

          <div className="mb-3 space-y-1 rounded-lg bg-card px-3 py-2 text-xs text-muted-foreground">
            <div>
              Est. {side === "BUY" ? "cost" : "proceeds"}
              <span className="float-right font-mono text-foreground">{sel ? money(estCost) : "—"}</span>
            </div>
            <div>
              Buying power after
              <span className={`float-right font-mono ${bpAfter < 0 ? "text-down" : "text-foreground"}`}>
                {acct ? money(bpAfter) : "—"}
              </span>
            </div>
          </div>

          <button
            onClick={submitOrder}
            disabled={!started}
            className={`w-full rounded-lg py-2.5 text-sm font-semibold text-white transition disabled:opacity-40 ${
              side === "BUY" ? "bg-up hover:bg-up/90" : "bg-down hover:bg-down/90"
            }`}
          >
            {side} {qty} {selected}
          </button>
          {!started && (
            <p className="mt-2 text-center text-xs text-muted-foreground">Open the market to trade.</p>
          )}

          {/* Account panel */}
          <div className="mt-6 space-y-1.5 border-t border-border pt-4 text-sm">
            <AcctRow label="Cash" value={money(acct?.cash_available)} />
            <AcctRow label="Cash locked" value={money(acct?.cash_locked)} />
            <AcctRow label="Equity" value={money(acct?.equity)} />
            <AcctRow label="Buying power" value={money(acct?.buying_power)} />
            <AcctRow
              label="Maint. margin"
              value={money(acct?.maintenance_margin_req)}
            />
            <AcctRow
              label="Margin status"
              value={acct?.margin_status ?? "—"}
              cls={acct?.margin_status === "OK" ? "text-up" : "text-warning"}
            />
          </div>
        </div>
      </div>

      {/* Clock */}
      <ClockBar
        clock={state?.clock ?? null}
        started={started}
        playing={playing}
        speed={speed}
        onStart={onStart}
        onPlayPause={() => (playing ? pause() : play())}
        onStepOne={() => doStep(1)}
        onSpeed={setSpeed}
        onScrub={onScrub}
        scrubbing={scrubbing}
      />

      {toast && (
        <div className="pointer-events-none absolute bottom-20 left-1/2 z-30 -translate-x-1/2 rounded-lg bg-muted px-4 py-2 text-sm text-foreground">
          {toast}
        </div>
      )}

      {showAccount && state && (
        <AccountPanel
          accountId={accountId}
          state={state}
          equityHist={equityHist}
          initialEquity={initialEquity}
          onClose={() => setShowAccount(false)}
        />
      )}
    </div>
  );
}

function Stat({ label, value, cls }: { label: string; value: string; cls?: string }) {
  return (
    <div className="text-right">
      <div className="text-[10px] text-muted-foreground">{label}</div>
      <div className={`font-mono text-sm font-semibold ${cls ?? "text-foreground"}`}>{value}</div>
    </div>
  );
}

function TicketField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-3">
      <div className="mb-1 text-xs text-muted-foreground">{label}</div>
      {children}
    </div>
  );
}

function AcctRow({ label, value, cls }: { label: string; value: string; cls?: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className={`font-mono ${cls ?? "text-foreground"}`}>{value}</span>
    </div>
  );
}

function PositionsTable({
  positions,
  onFlatten,
}: {
  positions: Position[];
  onFlatten: (p: Position) => void;
}) {
  if (!positions.length)
    return <div className="py-6 text-center text-muted-foreground">No open positions.</div>;
  return (
    <table className="w-full">
      <thead className="text-muted-foreground">
        <tr className="text-left">
          <th className="pb-1">Instrument</th>
          <th className="pb-1 text-right">Qty</th>
          <th className="pb-1 text-right">Avg</th>
          <th className="pb-1 text-right">Mark</th>
          <th className="pb-1 text-right">Unreal. P&L</th>
          <th className="pb-1 text-right"></th>
        </tr>
      </thead>
      <tbody>
        {positions.map((p) => (
          <tr key={p.instrument_id} className="border-t border-border">
            <td className="py-1 text-foreground">{p.instrument_id.replace(/^(STOCK|OPTION):/, "")}</td>
            <td className="py-1 text-right">{p.qty}</td>
            <td className="py-1 text-right">{num(p.avg_price)}</td>
            <td className="py-1 text-right">{num(p.mark_price)}</td>
            <td className={`py-1 text-right ${pnlCls(p.unrealized_pnl)}`}>
              {p.unrealized_pnl >= 0 ? "+" : ""}
              {num(p.unrealized_pnl)}
            </td>
            <td className="py-1 text-right">
              <button
                onClick={() => onFlatten(p)}
                title="Flatten (market close)"
                className="broker-btn rounded bg-muted px-1.5 py-0.5 text-[11px] text-foreground hover:bg-accent"
              >
                Flatten
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function OrdersTable({
  orders,
  onCancel,
}: {
  orders: FullState["open_orders"];
  onCancel: (id: string) => void;
}) {
  if (!orders.length)
    return <div className="py-6 text-center text-muted-foreground">No working orders.</div>;
  return (
    <table className="w-full">
      <thead className="text-muted-foreground">
        <tr className="text-left">
          <th className="pb-1">Instrument</th>
          <th className="pb-1">Side</th>
          <th className="pb-1">Type</th>
          <th className="pb-1 text-right">Qty</th>
          <th className="pb-1 text-right">Limit</th>
          <th className="pb-1 text-right">Status</th>
          <th className="pb-1"></th>
        </tr>
      </thead>
      <tbody>
        {orders.map((o) => (
          <tr key={o.order_id} className="border-t border-border">
            <td className="py-1 text-foreground">{o.instrument_id.replace("STOCK:", "")}</td>
            <td className={o.side === "BUY" ? "text-up" : "text-down"}>{o.side}</td>
            <td className="text-muted-foreground">{o.order_type}</td>
            <td className="py-1 text-right">{o.qty}</td>
            <td className="py-1 text-right">{o.limit_price ? num(o.limit_price) : "—"}</td>
            <td className="py-1 text-right text-muted-foreground">{o.status}</td>
            <td className="py-1 text-right">
              <button onClick={() => onCancel(o.order_id)} className="text-muted-foreground hover:text-down">
                <X className="h-3.5 w-3.5" />
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function TradesTable({ trades }: { trades: FullState["trades"] }) {
  if (!trades.length)
    return <div className="py-6 text-center text-muted-foreground">No fills yet.</div>;
  return (
    <table className="w-full">
      <thead className="text-muted-foreground">
        <tr className="text-left">
          <th className="pb-1">Time</th>
          <th className="pb-1">Instrument</th>
          <th className="pb-1">Side</th>
          <th className="pb-1 text-right">Qty</th>
          <th className="pb-1 text-right">Price</th>
        </tr>
      </thead>
      <tbody>
        {trades
          .slice()
          .reverse()
          .map((t, i) => {
            const inst = String(t.instrument_id ?? t.symbol ?? "").replace("STOCK:", "");
            const s = String(t.side ?? "");
            return (
              <tr key={i} className="border-t border-border">
                <td className="py-1 text-muted-foreground">{t.ts ? fmtET(String(t.ts)) : "—"}</td>
                <td className="py-1 text-foreground">{inst}</td>
                <td className={s === "BUY" ? "text-up" : "text-down"}>{s}</td>
                <td className="py-1 text-right">{t.qty ?? "—"}</td>
                <td className="py-1 text-right">{t.price ? num(Number(t.price)) : "—"}</td>
              </tr>
            );
          })}
      </tbody>
    </table>
  );
}
