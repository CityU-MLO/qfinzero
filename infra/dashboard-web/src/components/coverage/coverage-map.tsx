"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, Loader2, Minus, Newspaper, RefreshCw, X } from "lucide-react";

import { useLocale, useT } from "@/components/locale-provider";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

// ── types of /api/coverage/* ──────────────────────────────────────────────

type LevelId = "daily" | "minute" | "quotes" | "options_eod" | "options_minute" | "options_quotes"
  | "futures_daily" | "futures_minute" | "futures_quotes";
type CellLevels = Partial<Record<LevelId, number>> & { contracts?: number; sessions?: Record<string, number> };
interface Earnings { date: string; time_utc: string; title: string; status?: string; actual_eps?: number | null; estimated_eps?: number | null }
interface Macro { date: string; time_utc: string; title: string; importance?: string; actual?: string | null; consensus?: string | null }
interface Events { news: Record<string, Record<string, number>>; earnings: Record<string, Earnings[]>; macro: Macro[]; notes: string[] }
interface Matrix { tickers: string[]; days: string[]; levels: LevelId[]; cells: Record<string, Record<string, CellLevels>>; events?: Events }
interface Extent { stores: Record<LevelId, { start: string; end: string; days: number } | null>; default: { start: string; end: string }; suggested: { ticker: string }[] }
interface CellDetail {
  ticker: string;
  date: string;
  levels: Record<LevelId, { rows: number; contracts?: number; volume?: number; sessions?: Record<string, number> } | null>;
  daily_bar: { open: number; high: number; low: number; close: number; volume: number } | null;
  minute_span: { first_ns: number; last_ns: number } | null;
  quote_span: { first_ns: number; last_ns: number } | null;
  option_expiries: { expiry: string; contracts: number; volume: number }[];
  corporate_actions: { type: "split" | "dividend"; ratio?: number; cash?: number }[];
  events: { earnings: Earnings[]; macro: Macro[]; news: { id: string; time_utc: string; title: string; publisher?: string; url?: string }[]; notes: string[] };
}

const LEVELS: { id: LevelId; en: string; zh: string; short: string }[] = [
  { id: "daily", en: "Daily bars", zh: "日线", short: "D" },
  { id: "minute", en: "Minute bars", zh: "分钟线", short: "M" },
  { id: "quotes", en: "Stock quotes", zh: "股票报价", short: "Q" },
  { id: "options_eod", en: "Options EOD", zh: "期权日线", short: "OD" },
  { id: "options_minute", en: "Options minute", zh: "期权分钟成交", short: "OM" },
  { id: "options_quotes", en: "Options quotes", zh: "期权报价", short: "OQ" },
  { id: "futures_daily", en: "Futures daily", zh: "期货日线", short: "FD" },
  { id: "futures_minute", en: "Futures minute", zh: "期货分钟线", short: "FM" },
  { id: "futures_quotes", en: "Futures quotes", zh: "期货报价", short: "FQ" },
];
const SESSIONS = [
  { id: "overnight", en: "Overnight", zh: "夜盘", minutes: 480 },
  { id: "pre", en: "Pre-market", zh: "盘前", minutes: 330 },
  { id: "regular", en: "Regular", zh: "常规", minutes: 390 },
  { id: "post", en: "After-hours", zh: "盘后", minutes: 240 },
] as const;
const SHADES = [0, 0.16, 0.3, 0.45, 0.6, 0.78, 1];
const LABEL_W = 76;
const GAP = 2;

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((body as { detail?: string; error?: string }).detail ?? (body as { error?: string }).error ?? `HTTP ${r.status}`);
  return body as T;
}

function shiftDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

const etTime = (iso: string | number, locale: string) =>
  new Intl.DateTimeFormat(locale, { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false })
    .format(typeof iso === "number" ? new Date(iso / 1e6) : new Date(iso));

// ── ticker chips ──────────────────────────────────────────────────────────

function TickerInput({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const t = useT();
  const [text, setText] = React.useState("");
  const [open, setOpen] = React.useState(false);
  const q = text.trim().toUpperCase();
  const sugg = useQuery({
    queryKey: ["coverage", "suggest", q],
    queryFn: () => getJson<{ tickers: { ticker: string; dollar_volume: number }[] }>(`/api/coverage/suggest?q=${encodeURIComponent(q)}&limit=8`),
    enabled: open && q.length > 0,
    staleTime: 60_000,
  });
  const add = (s: string) => {
    const items = s.split(/[\s,]+/).map((x) => x.trim().toUpperCase()).filter(Boolean);
    const next = [...value];
    for (const x of items) if (!next.includes(x)) next.push(x);
    onChange(next.slice(0, 60));
    setText("");
  };
  return (
    <div className="relative">
      <div className="flex min-h-9 flex-wrap items-center gap-1 rounded-md border border-input bg-card px-1.5 py-1 focus-within:border-ring">
        {value.map((x) => (
          <span key={x} className="inline-flex items-center gap-0.5 rounded-sm bg-secondary px-1.5 py-0.5 font-mono text-xs">
            {x}
            <button onClick={() => onChange(value.filter((y) => y !== x))} aria-label={t(`Remove ${x}`, `移除 ${x}`)} className="text-muted-foreground hover:text-foreground">
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
        <input
          value={text}
          onChange={(e) => { setText(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={(e) => {
            if ((e.key === "Enter" || e.key === ",") && text.trim()) { e.preventDefault(); add(text); }
            if (e.key === "Backspace" && !text && value.length) onChange(value.slice(0, -1));
          }}
          placeholder={value.length ? "" : t("Add tickers, e.g. SPY QQQ", "添加代码，例如 SPY QQQ")}
          className="min-w-[8rem] flex-1 bg-transparent px-1 py-0.5 font-mono text-[13px] outline-none"
        />
      </div>
      {open && q && (sugg.data?.tickers.length ?? 0) > 0 && (
        <ul className="absolute z-20 mt-1 w-56 overflow-hidden rounded-md border bg-card py-1 text-[13px]">
          {sugg.data!.tickers.map((s) => (
            <li key={s.ticker}>
              <button onMouseDown={(e) => { e.preventDefault(); add(s.ticker); }}
                className="flex w-full justify-between px-2.5 py-1 hover:bg-accent">
                <span className="font-mono">{s.ticker}</span>
                <span className="text-xs tabular-nums text-muted-foreground">${(s.dollar_volume / 1e6).toFixed(0)}M</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── the map ───────────────────────────────────────────────────────────────

export function CoverageMap() {
  const t = useT();
  const { locale } = useLocale();
  const L = (x: { en: string; zh: string }) => (locale === "zh" ? x.zh : x.en);
  const intl = locale === "zh" ? "zh-CN" : "en-US";

  const extent = useQuery({ queryKey: ["coverage", "extent"], queryFn: () => getJson<Extent>("/api/coverage/extent"), staleTime: 300_000 });
  const [tickers, setTickers] = React.useState<string[]>([]);
  const [range, setRange] = React.useState<{ start: string; end: string } | null>(null);
  const [color, setColor] = React.useState<"all" | LevelId>("all");
  const [show, setShow] = React.useState({ news: true, earnings: true, macro: true });
  const [selected, setSelected] = React.useState<{ ticker: string; date: string } | null>(null);

  React.useEffect(() => {
    if (!extent.data) return;
    if (!range) setRange(extent.data.default);
    if (!tickers.length) setTickers(extent.data.suggested.map((s) => s.ticker).slice(0, 12));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [extent.data]);

  const ready = Boolean(range && tickers.length);
  const matrix = useQuery({
    queryKey: ["coverage", "matrix", tickers.join(","), range?.start, range?.end],
    queryFn: () => getJson<Matrix>(`/api/coverage/matrix?tickers=${encodeURIComponent(tickers.join(","))}&start=${range!.start}&end=${range!.end}`),
    enabled: ready,
    staleTime: 60_000,
  });

  // column width from the available space
  const wrap = React.useRef<HTMLDivElement>(null);
  const [width, setWidth] = React.useState(900);
  React.useEffect(() => {
    if (!wrap.current) return;
    const ro = new ResizeObserver((e) => setWidth(e[0].contentRect.width));
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);
  const days = matrix.data?.days ?? [];
  const W = days.length ? Math.max(8, Math.min(26, Math.floor((width - LABEL_W) / days.length) - GAP)) : 16;
  const cols = `${LABEL_W}px repeat(${days.length}, ${W}px)`;
  // label a month where it starts, unless its run is too short for the text
  const monthStart = (i: number) => {
    if (i > 0 && days[i].slice(0, 7) === days[i - 1].slice(0, 7)) return false;
    let run = 0;
    while (i + run < days.length && days[i + run].slice(0, 7) === days[i].slice(0, 7)) run += 1;
    return run * (W + GAP) >= 64 || i + run === days.length;
  };

  const maxRows = React.useMemo(() => {
    const m: Partial<Record<LevelId, number>> = {};
    for (const row of Object.values(matrix.data?.cells ?? {}))
      for (const c of Object.values(row)) for (const lv of LEVELS) m[lv.id] = Math.max(m[lv.id] ?? 0, c[lv.id] ?? 0);
    return m;
  }, [matrix.data]);

  const macroByDay = React.useMemo(() => {
    const m: Record<string, Macro[]> = {};
    for (const e of matrix.data?.events?.macro ?? []) (m[e.date] ??= []).push(e);
    return m;
  }, [matrix.data]);
  const earnByKey = React.useMemo(() => {
    const m: Record<string, Earnings> = {};
    for (const [tk, list] of Object.entries(matrix.data?.events?.earnings ?? {})) for (const e of list) m[`${tk}|${e.date}`] = e;
    return m;
  }, [matrix.data]);

  function cellStyle(c: CellLevels | undefined): React.CSSProperties {
    if (!c) return { background: "hsl(var(--muted))" };
    if (color === "all") {
      const n = LEVELS.filter((lv) => (c[lv.id] ?? 0) > 0).length;
      return { background: n ? `hsl(var(--primary) / ${SHADES[Math.min(n, SHADES.length - 1)]})` : "hsl(var(--muted))" };
    }
    const v = c[color] ?? 0;
    if (!v) return { background: "hsl(var(--muted))" };
    const a = 0.3 + 0.7 * (Math.log1p(v) / Math.log1p(maxRows[color] ?? v));
    return { background: `hsl(var(--primary) / ${a.toFixed(2)})` };
  }

  function cellTitle(tk: string, d: string, c: CellLevels | undefined, news: number, earn?: Earnings) {
    const parts = LEVELS.filter((lv) => (c?.[lv.id] ?? 0) > 0).map((lv) =>
      lv.id === "options_eod" && c?.contracts ? `${L(lv)} (${c.contracts} ${t("contracts", "个合约")})` :
      lv.id === "minute" ? `${L(lv)} (${c?.minute})` : L(lv));
    const lines = [`${tk} · ${d}`, parts.length ? parts.join(", ") : t("no data", "无数据")];
    if (news) lines.push(t(`${news} news`, `${news} 条新闻`));
    if (earn) lines.push(`${t("Earnings", "财报")}: ${earn.title}`);
    return lines.join("\n");
  }

  const preset = (days: number) => {
    const end = extent.data?.stores.daily?.end ?? range?.end;
    if (end) setRange({ start: shiftDays(end, -days), end });
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="grid gap-3 p-4 lg:grid-cols-[1fr_auto]">
          <TickerInput value={tickers} onChange={setTickers} />
          <div className="flex flex-wrap items-center gap-2">
            <input type="date" value={range?.start ?? ""} max={range?.end}
              onChange={(e) => range && setRange({ ...range, start: e.target.value })}
              className="h-9 rounded-md border border-input bg-card px-2 text-[13px]" aria-label={t("Start", "开始")} />
            <span className="text-muted-foreground">–</span>
            <input type="date" value={range?.end ?? ""} min={range?.start}
              onChange={(e) => range && setRange({ ...range, end: e.target.value })}
              className="h-9 rounded-md border border-input bg-card px-2 text-[13px]" aria-label={t("End", "结束")} />
            <div className="inline-flex rounded-md border bg-card p-0.5">
              {([["1M", 31], ["3M", 92], ["6M", 183], ["1Y", 366]] as const).map(([k, n]) => (
                <button key={k} onClick={() => preset(n)} className="rounded-sm px-2 py-1 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground">{k}</button>
              ))}
            </div>
            <Button size="icon" variant="outline" onClick={() => matrix.refetch()} title={t("Refresh", "刷新")}>
              <RefreshCw className={matrix.isFetching ? "animate-spin" : ""} />
            </Button>
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[13px] lg:col-span-2">
            <label className="flex items-center gap-2">
              <span className="text-muted-foreground">{t("Color by", "着色依据")}</span>
              <select value={color} onChange={(e) => setColor(e.target.value as typeof color)} className="h-8 rounded-md border border-input bg-card px-2">
                <option value="all">{t("Number of data levels", "可用数据层数")}</option>
                {LEVELS.map((lv) => <option key={lv.id} value={lv.id}>{L(lv)}</option>)}
              </select>
            </label>
            <span className="text-muted-foreground">{t("Show", "显示")}</span>
            {([["news", t("News", "新闻")], ["earnings", t("Earnings", "财报")], ["macro", t("Macro", "宏观")]] as const).map(([k, label]) => (
              <label key={k} className="flex items-center gap-1.5">
                <input type="checkbox" checked={show[k]} onChange={(e) => setShow({ ...show, [k]: e.target.checked })} />
                {label}
              </label>
            ))}
          </div>
        </CardContent>
      </Card>

      {extent.isError && <Alert variant="error" title={t("Coverage is unavailable", "覆盖信息不可用")}>{(extent.error as Error).message}</Alert>}
      {matrix.isError && <Alert variant="error" title={t("Could not load the map", "无法加载覆盖图")}>{(matrix.error as Error).message}</Alert>}
      {(matrix.data?.events?.notes?.length ?? 0) > 0 && (
        <Alert variant="warning">{t("Some events are missing: ", "部分事件缺失：")}{matrix.data!.events!.notes.join("; ")}</Alert>
      )}

      <Card>
        <CardContent className="p-4">
          <div ref={wrap} className="relative overflow-x-auto">
            {(matrix.isLoading || (!matrix.data && ready)) && (
              <div className="flex h-40 items-center justify-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" /> {t("Reading partitions…", "正在读取分区…")}
              </div>
            )}
            {matrix.data && days.length === 0 && (
              <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">{t("No data in this range.", "此区间没有数据。")}</div>
            )}
            {matrix.data && days.length > 0 && (
              <div className="inline-block min-w-full select-none text-[11px]" role="grid" aria-label={t("Data coverage", "数据覆盖")}>
                {/* month row */}
                <div className="grid" style={{ gridTemplateColumns: cols, columnGap: GAP }}>
                  <div />
                  {days.map((d, i) => (
                    <div key={d} className="relative h-4">
                      {monthStart(i) && (
                        <span className="absolute left-0 top-0 whitespace-nowrap font-medium text-foreground">
                          {new Intl.DateTimeFormat(intl, { year: "numeric", month: "short" }).format(new Date(`${d}T12:00:00Z`))}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
                {/* day-of-month row: Mondays */}
                <div className="grid border-b pb-1" style={{ gridTemplateColumns: cols, columnGap: GAP }}>
                  <div />
                  {days.map((d) => (
                    <div key={d} className="h-4 text-center tabular-nums text-muted-foreground">
                      {new Date(`${d}T12:00:00Z`).getUTCDay() === 1 ? Number(d.slice(8)) : ""}
                    </div>
                  ))}
                </div>
                {/* macro lane */}
                {show.macro && (
                  <div className="grid items-center border-b py-1" style={{ gridTemplateColumns: cols, columnGap: GAP }}>
                    <div className="truncate pr-2 text-muted-foreground">{t("Macro", "宏观")}</div>
                    {days.map((d) => {
                      const ev = macroByDay[d];
                      const high = ev?.some((e) => e.importance === "high");
                      return (
                        <div key={d} className="flex h-4 items-center justify-center" title={ev?.map((e) => `${etTime(e.time_utc, intl)} ET  ${e.title}${e.actual ? ` = ${e.actual}` : ""}`).join("\n")}>
                          {ev && <span className={cn("h-2 w-2 rotate-45 border border-warning", high && "bg-warning")} />}
                        </div>
                      );
                    })}
                  </div>
                )}
                {/* ticker rows */}
                <div className="mt-1 space-y-[2px]">
                  {matrix.data.tickers.map((tk) => (
                    <div key={tk} className="grid items-center" style={{ gridTemplateColumns: cols, columnGap: GAP }} role="row">
                      <div className="truncate pr-2 font-mono text-xs font-medium" title={tk}>{tk}</div>
                      {days.map((d) => {
                        const c = matrix.data!.cells[tk]?.[d];
                        const news = show.news ? matrix.data!.events?.news?.[tk]?.[d] ?? 0 : 0;
                        const earn = show.earnings ? earnByKey[`${tk}|${d}`] : undefined;
                        const on = selected?.ticker === tk && selected.date === d;
                        return (
                          <button
                            key={d}
                            role="gridcell"
                            onClick={() => setSelected(on ? null : { ticker: tk, date: d })}
                            title={cellTitle(tk, d, c, news, earn)}
                            style={{ ...cellStyle(c), height: Math.max(14, Math.min(22, W)) }}
                            className={cn("relative rounded-[2px] transition-[outline] hover:outline hover:outline-1 hover:outline-foreground/50",
                              on && "outline outline-2 outline-foreground")}
                          >
                            {earn && <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full border border-card bg-warning" />}
                            {news > 0 && (
                              <span className="absolute inset-x-0.5 bottom-0.5 h-[3px] rounded-full"
                                style={{ background: `hsl(var(--chart-4) / ${Math.min(1, 0.35 + news * 0.15)})` }} />
                            )}
                          </button>
                        );
                      })}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* legend */}
          <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 border-t pt-3 text-xs text-muted-foreground">
            {color === "all" ? (
              <span className="flex items-center gap-1.5">
                {t("Data levels", "数据层数")}
                {SHADES.map((a, i) => (
                  <span key={i} className="flex flex-col items-center">
                    <span className="h-3 w-4 rounded-[2px]" style={{ background: i ? `hsl(var(--primary) / ${a})` : "hsl(var(--muted))" }} />
                  </span>
                ))}
                <span className="tabular-nums">0 → 6</span>
              </span>
            ) : (
              <span className="flex items-center gap-1.5">
                {L(LEVELS.find((lv) => lv.id === color)!)}
                <span className="h-3 w-4 rounded-[2px] bg-muted" /> {t("none", "无")}
                <span className="h-3 w-4 rounded-[2px]" style={{ background: "hsl(var(--primary) / 0.35)" }} />
                <span className="h-3 w-4 rounded-[2px]" style={{ background: "hsl(var(--primary))" }} /> {t("more rows", "行数更多")}
              </span>
            )}
            <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-warning" /> {t("earnings", "财报")}</span>
            <span className="flex items-center gap-1.5"><span className="h-[3px] w-4 rounded-full" style={{ background: "hsl(var(--chart-4))" }} /> {t("news", "新闻")}</span>
            <span className="flex items-center gap-1.5"><span className="h-2 w-2 rotate-45 bg-warning" /> {t("macro release", "宏观数据发布")}</span>
            <span className="ml-auto">{t("Levels:", "数据层：")} {LEVELS.map((lv) => L(lv)).join(" · ")}</span>
          </div>
        </CardContent>
      </Card>

      {selected && <CellPanel ticker={selected.ticker} date={selected.date} onClose={() => setSelected(null)} />}
    </div>
  );
}

// ── detail of one cell ────────────────────────────────────────────────────

function CellPanel({ ticker, date, onClose }: { ticker: string; date: string; onClose: () => void }) {
  const t = useT();
  const { locale } = useLocale();
  const intl = locale === "zh" ? "zh-CN" : "en-US";
  const L = (x: { en: string; zh: string }) => (locale === "zh" ? x.zh : x.en);
  const q = useQuery({
    queryKey: ["coverage", "cell", ticker, date],
    queryFn: () => getJson<CellDetail>(`/api/coverage/cell?ticker=${encodeURIComponent(ticker)}&date=${date}`),
  });
  const c = q.data;
  const weekday = new Intl.DateTimeFormat(intl, { weekday: "long", timeZone: "UTC" }).format(new Date(`${date}T12:00:00Z`));
  const num = (x: number) => x.toLocaleString(intl);

  return (
    <aside className="fixed bottom-0 right-0 top-12 z-30 flex w-full max-w-md flex-col border-l bg-card" aria-label={t("Cell details", "单元格详情")}>
      <div className="flex items-start justify-between border-b px-4 py-3">
        <div>
          <div className="font-mono text-base font-semibold">{ticker}</div>
          <div className="text-xs text-muted-foreground">{date} · {weekday}</div>
        </div>
        <button onClick={onClose} className="rounded-md p-1 text-muted-foreground hover:bg-accent" aria-label={t("Close", "关闭")}><X className="h-4 w-4" /></button>
      </div>
      <div className="flex-1 space-y-5 overflow-y-auto p-4 text-[13px]">
        {q.isLoading && <div className="flex items-center gap-2 text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> {t("Loading…", "加载中…")}</div>}
        {q.isError && <Alert variant="error">{(q.error as Error).message}</Alert>}
        {c && (
          <>
            {c.daily_bar && (
              <div className="grid grid-cols-5 gap-2 rounded-md border px-3 py-2 tabular-nums">
                {([["O", c.daily_bar.open], ["H", c.daily_bar.high], ["L", c.daily_bar.low], ["C", c.daily_bar.close]] as const).map(([k, v]) => (
                  <div key={k}><div className="text-[11px] text-muted-foreground">{k}</div><div className="font-medium">{v.toFixed(2)}</div></div>
                ))}
                <div><div className="text-[11px] text-muted-foreground">{t("Vol", "量")}</div><div className="font-medium">{num(c.daily_bar.volume)}</div></div>
              </div>
            )}

            <section>
              <h3 className="mb-2 text-xs font-semibold text-muted-foreground">{t("Data levels", "数据层")}</h3>
              <ul className="divide-y rounded-md border">
                {LEVELS.map((lv) => {
                  const info = c.levels[lv.id];
                  const span = lv.id === "minute" ? c.minute_span : lv.id === "quotes" ? c.quote_span : null;
                  return (
                    <li key={lv.id} className="flex items-center gap-2 px-3 py-2">
                      {info ? <Check className="h-4 w-4 text-success" /> : <Minus className="h-4 w-4 text-muted-foreground/60" />}
                      <span className={cn("flex-1", !info && "text-muted-foreground")}>{L(lv)}</span>
                      <span className="text-right text-xs tabular-nums text-muted-foreground">
                        {info ? (
                          <>
                            {num(info.rows)} {t("rows", "行")}
                            {info.contracts !== undefined && ` · ${num(info.contracts)} ${t("contracts", "个合约")}`}
                            {span && ` · ${etTime(span.first_ns, intl)}–${etTime(span.last_ns, intl)} ET`}
                          </>
                        ) : t("none", "无")}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </section>

            {c.levels.minute?.sessions && (
              <section>
                <h3 className="mb-2 text-xs font-semibold text-muted-foreground">{t("Minute bars by session (ET)", "各时段分钟线（美东）")}</h3>
                <div className="flex overflow-hidden rounded-md border">
                  {SESSIONS.map((s) => {
                    const n = c.levels.minute!.sessions![s.id] ?? 0;
                    const ratio = Math.min(1, n / s.minutes);
                    return (
                      <div key={s.id} className="border-r px-2 py-1.5 last:border-r-0" style={{ flex: s.minutes, background: `hsl(var(--primary) / ${(ratio * 0.35).toFixed(2)})` }}
                        title={`${L(s)}: ${n} / ${s.minutes}`}>
                        <div className="truncate text-[11px] text-muted-foreground">{L(s)}</div>
                        <div className="font-medium tabular-nums">{n}</div>
                      </div>
                    );
                  })}
                </div>
              </section>
            )}

            {c.option_expiries.length > 0 && (
              <section>
                <h3 className="mb-2 text-xs font-semibold text-muted-foreground">
                  {t(`Option expiries (${c.option_expiries.length})`, `期权到期日（${c.option_expiries.length}）`)}
                </h3>
                <table className="w-full text-xs">
                  <thead className="text-muted-foreground"><tr><th className="py-1 text-left font-medium">{t("Expiry", "到期日")}</th><th className="text-right font-medium">{t("Contracts", "合约数")}</th><th className="text-right font-medium">{t("Volume", "成交量")}</th></tr></thead>
                  <tbody>
                    {c.option_expiries.slice(0, 10).map((e) => (
                      <tr key={e.expiry} className="border-t"><td className="py-1 font-mono">{e.expiry}</td><td className="text-right">{num(e.contracts)}</td><td className="text-right">{num(e.volume)}</td></tr>
                    ))}
                  </tbody>
                </table>
              </section>
            )}

            {(c.corporate_actions.length > 0 || c.events.earnings.length > 0) && (
              <section className="space-y-2">
                <h3 className="text-xs font-semibold text-muted-foreground">{t("Corporate events", "公司事件")}</h3>
                {c.corporate_actions.map((a, i) => (
                  <div key={i} className="flex items-center gap-2"><Badge variant="secondary">{a.type === "split" ? t("Split", "拆股") : t("Dividend", "分红")}</Badge>
                    {a.type === "split" ? `${a.ratio}:1` : `$${a.cash?.toFixed(2)}`} · {t("ex-date", "除权日")}</div>
                ))}
                {c.events.earnings.map((e) => (
                  <div key={e.time_utc} className="rounded-md border px-3 py-2">
                    <div className="flex items-center gap-2"><Badge variant="warn">{t("Earnings", "财报")}</Badge><span className="text-muted-foreground">{etTime(e.time_utc, intl)} ET</span></div>
                    <div className="mt-1 font-medium">{e.title}</div>
                    {e.estimated_eps != null && (
                      <div className="mt-0.5 tabular-nums text-muted-foreground">
                        EPS {e.actual_eps ?? "—"} {t("vs est.", "对比预期")} {e.estimated_eps}
                      </div>
                    )}
                  </div>
                ))}
              </section>
            )}

            {c.events.macro.length > 0 && (
              <section>
                <h3 className="mb-2 text-xs font-semibold text-muted-foreground">{t("Macro releases", "宏观数据")}</h3>
                <ul className="space-y-1">
                  {c.events.macro.map((m) => (
                    <li key={m.time_utc + m.title} className="flex gap-2">
                      <span className="w-12 shrink-0 tabular-nums text-muted-foreground">{etTime(m.time_utc, intl)}</span>
                      <span className="flex-1">{m.title}</span>
                      <span className="tabular-nums text-muted-foreground">{m.actual ?? m.consensus ?? ""}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <section>
              <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
                <Newspaper className="h-3.5 w-3.5" /> {t(`News (${c.events.news.length})`, `新闻（${c.events.news.length}）`)}
              </h3>
              {c.events.news.length === 0 ? (
                <p className="text-muted-foreground">{t("No articles on this day.", "当天没有新闻。")}</p>
              ) : (
                <ul className="space-y-2">
                  {c.events.news.map((n) => (
                    <li key={n.id} className="flex gap-2">
                      <span className="w-12 shrink-0 tabular-nums text-muted-foreground">{etTime(n.time_utc, intl)}</span>
                      <span className="flex-1">
                        {n.url ? <a href={n.url} target="_blank" rel="noopener noreferrer" className="hover:text-primary hover:underline">{n.title}</a> : n.title}
                        {n.publisher && <span className="block text-[11px] text-muted-foreground">{n.publisher}</span>}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            {c.events.notes.length > 0 && <Alert variant="warning">{c.events.notes.join("; ")}</Alert>}
          </>
        )}
      </div>
    </aside>
  );
}
