"use client";

// QFZView: a TradingView-style market viewer over whatever the store holds.
// Pick a stock, future (/CL), crypto pair (X:BTC-USD), FX pair (C:EUR-USD) or
// option contract (O:...); the intervals, quote overlay and ranges offered are
// those the store has data for. Scroll left to load older history. US stock
// minute charts shade the overnight (Blue Ocean), pre-market and after-hours
// sessions and can show all of them, the extended day or the regular session.
// Stocks and option contracts open the underlying's option chain beside the
// chart; clicking a contract charts it.

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, CandlestickChart, Info, Layers, Loader2, Plus, Search, Star, X } from "lucide-react";

import { useLocale, useT } from "@/components/locale-provider";
import {
  SESSION_LABEL, SESSION_SHADE, TradingChart, type Indicators, type Overlay,
} from "@/components/charts/trading-chart";
import {
  aggregate, filterSessions, INTERVALS, mergeBars, SESSIONS, type Bar, type Interval, type SessionFilter,
} from "@/lib/bars";
import {
  addDays, extent as loadExtent, isoDay, kindOf, LEVELS, loadBars, loadQuotes, parseOption, suggest, zoneOf, type Kind,
} from "@/lib/qfzview";
import { OptionChainPanel } from "@/components/qfzview/option-chain-panel";
import { cn } from "@/lib/utils";

const DEFAULT_WATCH = ["SPY", "QQQ", "AAPL", "NVDA", "/CL", "/ZN", "X:BTC-USD", "X:ETH-USD", "C:EUR-USD", "C:USD-JPY"];
const KIND_LABEL: Record<Kind, [string, string]> = {
  stock: ["Stock", "股票"], future: ["Future", "期货"], crypto: ["Crypto", "加密货币"], fx: ["FX", "外汇"], option: ["Option", "期权"],
};
const SESSION_FILTERS: { id: SessionFilter; label: [string, string]; hint: [string, string] }[] = [
  { id: "all", label: ["All", "全部"], hint: ["Overnight, pre-market, regular and after-hours", "夜盘、盘前、盘中和盘后"] },
  { id: "extended", label: ["Extended", "盘前盘后"], hint: ["04:00-20:00 ET, without the overnight session", "美东 04:00-20:00，不含夜盘"] },
  { id: "regular", label: ["Regular", "仅盘中"], hint: ["09:30-16:00 ET only", "只看美东 09:30-16:00"] },
];
const KIND_TONE: Record<Kind, string> = {
  stock: "bg-primary/10 text-primary", future: "bg-amber-500/10 text-amber-700", crypto: "bg-violet-500/10 text-violet-700",
  fx: "bg-emerald-500/10 text-emerald-700", option: "bg-sky-500/10 text-sky-700",
};

function useStored<T>(key: string, initial: T): [T, (v: T) => void] {
  const [v, setV] = React.useState<T>(initial);
  React.useEffect(() => {
    try {
      const s = localStorage.getItem(key);
      if (s) setV(JSON.parse(s));
    } catch { /* private mode: keep the default */ }
  }, [key]);
  const set = React.useCallback((x: T) => {
    setV(x);
    try { localStorage.setItem(key, JSON.stringify(x)); } catch { /* ignore */ }
  }, [key]);
  return [v, set];
}

function KindBadge({ kind }: { kind: Kind }) {
  const t = useT();
  return <span className={cn("rounded px-1.5 py-px text-[10px] font-semibold", KIND_TONE[kind])}>{t(...KIND_LABEL[kind])}</span>;
}

function SymbolSearch({ onPick }: { onPick: (s: string) => void }) {
  const t = useT();
  const [q, setQ] = React.useState("");
  const [open, setOpen] = React.useState(false);
  const sugg = useQuery({ queryKey: ["qfzview", "suggest", q], queryFn: () => suggest(q), enabled: open, staleTime: 60_000 });
  const pick = (s: string) => { onPick(s.trim().toUpperCase()); setQ(""); setOpen(false); };
  return (
    <div className="relative">
      <div className="flex h-8 w-64 items-center gap-2 rounded-md border bg-background px-2">
        <Search className="h-3.5 w-3.5 text-muted-foreground" />
        <input value={q} onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)}
               onBlur={() => setTimeout(() => setOpen(false), 150)}
               onKeyDown={(e) => { if (e.key === "Enter" && q.trim()) pick(q); }}
               placeholder={t("SPY, /CL, X:BTC-USD, C:EUR-USD, O:…", "SPY、/CL、X:BTC-USD、C:EUR-USD、O:…")}
               className="w-full bg-transparent font-mono text-[13px] outline-none placeholder:font-sans placeholder:text-muted-foreground" />
      </div>
      {open && (sugg.data?.length ?? 0) > 0 && (
        <ul className="absolute z-30 mt-1 w-72 overflow-hidden rounded-md border bg-card py-1 text-[13px] shadow-lg">
          {sugg.data!.map((s) => (
            <li key={s.ticker}>
              <button onMouseDown={(e) => { e.preventDefault(); pick(s.ticker); }}
                      className="flex w-full items-center justify-between px-3 py-1.5 hover:bg-accent">
                <span className="font-mono">{s.ticker}</span>
                <KindBadge kind={kindOf(s.ticker).kind} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface Series { key: string; bars: Bar[]; start: string | null; done: boolean; error?: string }

export function QFZView() {
  const t = useT();
  const { locale } = useLocale();
  const router = useRouter();
  const params = useSearchParams();
  const symbol = (params.get("s") ?? "SPY").toUpperCase();
  const interval = (Number(params.get("i")) || 5) as Interval;
  const { kind } = kindOf(symbol);
  const zone = zoneOf(kind);
  const [watch, setWatch] = useStored<string[]>("qfzview.watch", DEFAULT_WATCH);
  const [ind, setInd] = useStored<Indicators>("qfzview.indicators", { ma: [20], ema: [], bb: false, vwap: false });
  const [showQuotes, setShowQuotes] = React.useState(false);
  const [sessFilter, setSessFilter] = useStored<SessionFilter>("qfzview.sessions", "all");
  const [chainOpen, setChainOpen] = React.useState(false);
  const opt = kind === "option" ? parseOption(symbol) : null;
  const chainUnderlying = kind === "stock" ? symbol : opt?.underlying ?? null;
  const ext = useQuery({ queryKey: ["qfzview", "extent"], queryFn: loadExtent, staleTime: 5 * 60_000 });

  const levels = LEVELS[kind];
  const stores = ext.data?.stores ?? {};
  const hasMinute = !!(levels.minute && stores[levels.minute]);
  const hasDaily = !!(levels.daily && stores[levels.daily]);
  const hasQuotes = !!(levels.quotes && stores[levels.quotes]);
  const offered = INTERVALS.filter((x) => (x.id === 1440 ? hasDaily : hasMinute));
  const daily = interval === 1440;
  const sessionsOn = kind === "stock" && !daily;
  const storeEnd = (daily ? stores[levels.daily ?? ""] : stores[levels.minute ?? ""])?.end ?? isoDay(new Date());
  // a contract stops trading at its expiry: start there when the store reaches further
  const optExpiry = kind === "option" ? parseOption(symbol)?.expiry : undefined;
  const lastDay = optExpiry && optExpiry < storeEnd ? optExpiry : storeEnd;

  const set = React.useCallback((next: { s?: string; i?: number }) => {
    const p = new URLSearchParams(params.toString());
    if (next.s) p.set("s", next.s);
    if (next.i) p.set("i", String(next.i));
    router.replace(`/view?${p.toString()}`, { scroll: false });
  }, [params, router]);

  // fall back to an interval the symbol's kind has
  React.useEffect(() => {
    if (ext.data && offered.length && !offered.some((x) => x.id === interval)) set({ i: offered[offered.length - 1].id });
  }, [ext.data, offered, interval, set]);

  // raw bars (minute or daily) for the symbol, paged backwards
  const key = `${symbol}|${daily ? "D" : "M"}|${interval}`;
  const [series, setSeries] = React.useState<Series>({ key: "", bars: [], start: null, done: false });
  // one generation per symbol/interval: answers from an earlier one are dropped
  const gen = React.useRef(0);
  const loading = React.useRef(false);
  const empties = React.useRef(0);

  const loadPage = React.useCallback(async (end: string, reset: boolean) => {
    if (loading.current) return;
    loading.current = true;
    const g = gen.current;
    try {
      const page = await loadBars(symbol, interval, end);
      if (gen.current !== g) return;
      empties.current = page.bars.length ? 0 : empties.current + 1;
      setSeries((s) => ({
        key, bars: reset ? page.bars : mergeBars(page.bars, s.bars), start: page.start,
        done: empties.current >= (daily ? 2 : 6), error: undefined,
      }));
    } catch (e) {
      if (gen.current === g) setSeries((s) => ({ ...s, key, error: (e as Error).message, done: true }));
    } finally {
      if (gen.current === g) loading.current = false;
    }
  }, [symbol, interval, daily, key]);

  React.useEffect(() => {
    if (!ext.data || !offered.some((x) => x.id === interval)) return;
    gen.current += 1;
    empties.current = 0;
    loading.current = false;
    setSeries({ key, bars: [], start: null, done: false });
    void loadPage(lastDay, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, ext.data, lastDay]);

  const older = React.useCallback(() => {
    if (series.key !== key || !series.start || series.done) return;
    void loadPage(addDays(series.start, -1), false);
  }, [series.key, series.start, series.done, key, loadPage]);

  // keep paging through empty stretches (weekends, holidays) until something shows up
  React.useEffect(() => {
    if (series.key === key && series.start && !series.bars.length && !series.done && !loading.current) older();
  }, [series, older, key]);

  const shownBars = React.useMemo(() => (series.key === key ? series.bars : []), [series, key]);
  const bars = React.useMemo(() => (daily ? shownBars
    : aggregate(sessionsOn ? filterSessions(shownBars, sessFilter) : shownBars, interval, zone)),
  [shownBars, interval, zone, daily, sessionsOn, sessFilter]);

  // bid/ask overlay, bucketed onto the bars so both share the time axis
  const quotesOn = showQuotes && hasQuotes && !daily && interval <= 15;
  const quoteWindow = shownBars.length ? [shownBars[Math.max(0, shownBars.length - 2000)].ns, shownBars[shownBars.length - 1].ns] : null;
  const quotes = useQuery({
    queryKey: ["qfzview", "quotes", symbol, quoteWindow?.[0], quoteWindow?.[1]],
    queryFn: () => loadQuotes(symbol, quoteWindow![0], quoteWindow![1]),
    enabled: quotesOn && !!quoteWindow,
  });
  const overlays: Overlay[] = React.useMemo(() => {
    if (!quotesOn || !quotes.data?.length || !bars.length) return [];
    const bid: { ns: number; value: number }[] = [];
    const ask: { ns: number; value: number }[] = [];
    let j = 0;
    const q = quotes.data;
    for (let i = 0; i < bars.length; i++) {
      const endNs = i + 1 < bars.length ? bars[i + 1].ns : Infinity;
      let last: (typeof q)[number] | null = null;
      while (j < q.length && q[j].ns < endNs) {
        if (q[j].ns >= bars[i].ns) last = q[j];
        j++;
      }
      if (last) {
        bid.push({ ns: bars[i].ns, value: last.bid });
        ask.push({ ns: bars[i].ns, value: last.ask });
      }
    }
    return [{ id: "bid", title: "Bid", tone: "up", points: bid }, { id: "ask", title: "Ask", tone: "down", points: ask }];
  }, [quotesOn, quotes.data, bars]);

  const last = bars[bars.length - 1];
  const prev = bars[bars.length - 2];
  // the chain opens on the chart's last day, or the latest day with option minutes when that is earlier
  const optRange = stores[LEVELS.option.minute ?? ""] ?? null;
  const chainDay = (() => {
    const d = shownBars.length ? shownBars[shownBars.length - 1].day || isoDay(new Date(shownBars[shownBars.length - 1].ns / 1e6)) : lastDay;
    return optRange && d > optRange.end ? optRange.end : d;
  })();
  const chg = last && prev ? last.close - prev.close : null;
  const toggleMa = (n: number, list: "ma" | "ema") =>
    setInd({ ...ind, [list]: ind[list].includes(n) ? ind[list].filter((x) => x !== n) : [...ind[list], n].sort((a, b) => a - b) });
  const fmtRange = (s?: { start: string; end: string } | null) => (s ? `${s.start} → ${s.end}` : t("none", "无"));
  const intl = locale === "zh" ? "zh-CN" : "en-US";

  return (
    <div className="fixed inset-x-0 bottom-0 top-12 z-10 flex flex-col bg-background">
      {/* toolbar */}
      <div className="flex flex-wrap items-center gap-2 border-b bg-card px-3 py-2">
        <span className="mr-1 flex items-center gap-1.5 text-[13px] font-semibold"><CandlestickChart className="h-4 w-4 text-primary" />QFZView</span>
        <SymbolSearch onPick={(s) => set({ s })} />
        <div className="flex items-center gap-2 px-2">
          {opt && (
            <button onClick={() => set({ s: opt.underlying })} title={t(`Back to ${opt.underlying}`, `回到 ${opt.underlying}`)}
                    className="flex items-center gap-0.5 rounded px-1 py-0.5 text-[12px] text-primary hover:bg-primary/10">
              <ArrowLeft className="h-3.5 w-3.5" />{opt.underlying}
            </button>
          )}
          <span className="font-mono text-[15px] font-semibold">{symbol}</span>
          <KindBadge kind={kind} />
          {opt && (
            <span className="text-[12px] text-muted-foreground">
              {opt.expiry} · {opt.strike} {opt.right === "C" ? t("call", "看涨") : t("put", "看跌")}
            </span>
          )}
          {last && (
            <span className="font-mono text-[13px]">
              <b>{last.close.toLocaleString(intl, { maximumFractionDigits: 6 })}</b>
              {chg != null && <span className={cn("ml-1.5", chg >= 0 ? "text-up" : "text-down")}>{chg >= 0 ? "+" : ""}{(chg / prev!.close * 100).toFixed(2)}%</span>}
            </span>
          )}
        </div>
        <div className="flex rounded-md border bg-background p-0.5">
          {INTERVALS.map((x) => {
            const ok = offered.some((o) => o.id === x.id);
            return (
              <button key={x.id} disabled={!ok} onClick={() => set({ i: x.id })}
                      title={ok ? undefined : t("No data at this interval for this kind", "此类资产没有该周期的数据")}
                      className={cn("rounded px-2 py-0.5 text-[12px] font-medium", interval === x.id ? "bg-primary text-primary-foreground" : ok ? "text-muted-foreground hover:text-foreground" : "text-muted-foreground/40")}>
                {x.label}
              </button>
            );
          })}
        </div>
        {sessionsOn && (
          <div className="flex items-center gap-2">
            <div className="flex rounded-md border bg-background p-0.5">
              {SESSION_FILTERS.map((f) => (
                <button key={f.id} onClick={() => setSessFilter(f.id)} title={t(...f.hint)}
                        className={cn("rounded px-2 py-0.5 text-[12px] font-medium", sessFilter === f.id ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")}>
                  {t(...f.label)}
                </button>
              ))}
            </div>
            <div className="hidden items-center gap-2 text-[11px] text-muted-foreground xl:flex">
              {SESSIONS.filter((x) => sessFilter === "all" || (x !== "overnight" && (sessFilter === "extended" || x === "regular"))).map((x) => (
                <span key={x} className="flex items-center gap-1">
                  <span className="h-2.5 w-3.5 rounded-sm border" style={{ backgroundColor: `hsl(var(--foreground) / ${SESSION_SHADE[x]})` }} />
                  {t(...SESSION_LABEL[x])}
                </span>
              ))}
            </div>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-1 text-[12px]">
          {[["ma", 20], ["ma", 50], ["ema", 9], ["ema", 21]].map(([l, n]) => {
            const on = ind[l as "ma" | "ema"].includes(n as number);
            return <button key={`${l}${n}`} onClick={() => toggleMa(n as number, l as "ma" | "ema")}
                           className={cn("rounded-md border px-2 py-0.5", on ? "border-primary bg-primary/10 text-primary" : "text-muted-foreground hover:bg-accent")}>{String(l).toUpperCase()}{n}</button>;
          })}
          <button onClick={() => setInd({ ...ind, bb: !ind.bb })} className={cn("rounded-md border px-2 py-0.5", ind.bb ? "border-primary bg-primary/10 text-primary" : "text-muted-foreground hover:bg-accent")}>BB</button>
          {!daily && <button onClick={() => setInd({ ...ind, vwap: !ind.vwap })} className={cn("rounded-md border px-2 py-0.5", ind.vwap ? "border-primary bg-primary/10 text-primary" : "text-muted-foreground hover:bg-accent")}>VWAP</button>}
          {hasQuotes && !daily && interval <= 15 && (
            <button onClick={() => setShowQuotes(!showQuotes)} className={cn("rounded-md border px-2 py-0.5", showQuotes ? "border-primary bg-primary/10 text-primary" : "text-muted-foreground hover:bg-accent")}>
              {t("Bid/Ask", "买卖价")}{quotes.isFetching && <Loader2 className="ml-1 inline h-3 w-3 animate-spin" />}
            </button>
          )}
        </div>
        {chainUnderlying && (
          <button onClick={() => setChainOpen(!chainOpen)}
                  className={cn("flex items-center gap-1 rounded-md border px-2 py-0.5 text-[12px]", chainOpen ? "border-primary bg-primary/10 text-primary" : "text-muted-foreground hover:bg-accent")}>
            <Layers className="h-3.5 w-3.5" />{t("Option chain", "期权链")}
          </button>
        )}
        <div className="ml-auto flex items-center gap-2 text-[11px] text-muted-foreground">
          {loading.current && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {shownBars.length > 0 && <span>{t(`${bars.length.toLocaleString()} bars · ${zone === "et" ? "ET" : "UTC"}`, `${bars.length.toLocaleString()} 根 · ${zone === "et" ? "美东时间" : "UTC"}`)}</span>}
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        {/* chart */}
        <div className="relative min-w-0 flex-1">
          <TradingChart bars={bars} daily={daily} zone={zone} indicators={ind} overlays={overlays} onNeedOlder={older}
                        viewKey={key} sessions={sessionsOn ? { minutes: interval } : undefined}
                        empty={ext.isLoading || (!series.done && !series.error) ? <Loader2 className="h-5 w-5 animate-spin" />
                          : series.error ? <span className="text-destructive">{series.error}</span>
                            : t(`No ${daily ? "daily" : "minute"} data for ${symbol}.`, `${symbol} 没有${daily ? "日线" : "分钟"}数据。`)} />
        </div>

        {/* option chain (replaces the watchlist while open) */}
        {chainOpen && chainUnderlying && (
          <aside className="flex w-full max-w-[640px] shrink-0 flex-col border-l bg-card sm:w-[52%]">
            <OptionChainPanel underlying={chainUnderlying} highlight={kind === "option" ? symbol : undefined}
                              defaultDay={chainDay} range={optRange} onClose={() => setChainOpen(false)}
                              onPick={(c) => set({ s: c, i: interval === 1440 ? 1440 : Math.min(interval, 15) })} />
          </aside>
        )}

        {/* side panel */}
        <aside className={cn("hidden w-72 shrink-0 flex-col border-l bg-card lg:flex", chainOpen && chainUnderlying && "lg:hidden")}>
          <div className="flex items-center justify-between border-b px-3 py-2">
            <span className="flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wide text-muted-foreground"><Star className="h-3.5 w-3.5" />{t("Watchlist", "自选")}</span>
            {!watch.includes(symbol) && (
              <button onClick={() => setWatch([...watch, symbol])} className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[12px] text-primary hover:bg-primary/10"><Plus className="h-3 w-3" />{symbol}</button>
            )}
          </div>
          <ul className="min-h-0 flex-1 overflow-y-auto py-1">
            {watch.map((w) => (
              <li key={w} className={cn("group flex items-center gap-2 px-3 py-1.5 text-[13px]", w === symbol ? "bg-primary/[0.07]" : "hover:bg-accent/60")}>
                <button className="flex flex-1 items-center justify-between" onClick={() => set({ s: w })}>
                  <span className="font-mono">{w}</span>
                  <KindBadge kind={kindOf(w).kind} />
                </button>
                <button onClick={() => setWatch(watch.filter((x) => x !== w))} className="text-muted-foreground opacity-0 hover:text-foreground group-hover:opacity-100" aria-label={t("Remove", "移除")}><X className="h-3.5 w-3.5" /></button>
              </li>
            ))}
          </ul>
          <div className="border-t px-3 py-3 text-[12px]">
            <p className="mb-2 flex items-center gap-1.5 font-semibold text-muted-foreground"><Info className="h-3.5 w-3.5" />{t("Data in the store", "存储中的数据")} · <KindBadge kind={kind} /></p>
            <dl className="space-y-1">
              {(["daily", "minute", "quotes"] as const).map((lv) => levels[lv] && (
                <div key={lv} className="flex justify-between gap-2">
                  <dt className="text-muted-foreground">{lv === "daily" ? t("Daily", "日线") : lv === "minute" ? t("Minute", "分钟") : t("Quotes", "报价")}</dt>
                  <dd className="font-mono text-[11px]">{fmtRange(stores[levels[lv]!])}</dd>
                </div>
              ))}
            </dl>
            <p className="mt-2 text-[11px] text-muted-foreground">{t("Ranges are per store; a symbol may cover less. Scroll left for older bars.", "范围按存储统计，单个代码可能更短。向左拖动加载更早的数据。")}</p>
          </div>
        </aside>
      </div>
    </div>
  );
}
