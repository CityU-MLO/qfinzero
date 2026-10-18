"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { CalendarDays, ChevronLeft, ChevronRight, Loader2 } from "lucide-react";

import { useT } from "@/components/locale-provider";
import { cn } from "@/lib/utils";

type Days = Record<string, string[]>;
type DayInfo = { date: string; levels: Record<string, { tickers: number; top: string[] } | null> };

// what a trading session needs, in the order shown
const KINDS = [
  { id: "minute", en: "Stock minute bars", zh: "股票分钟线", dot: "bg-primary" },
  { id: "options_minute", en: "Options", zh: "期权", dot: "bg-violet-500" },
  { id: "futures_minute", en: "Futures", zh: "期货", dot: "bg-amber-500" },
] as const;

const iso = (d: Date) => d.toISOString().slice(0, 10);
const monthStart = (s: string) => `${s.slice(0, 7)}-01`;
function addMonths(s: string, n: number) {
  const d = new Date(`${monthStart(s)}T00:00:00Z`);
  d.setUTCMonth(d.getUTCMonth() + n);
  return iso(d);
}

/** A date field whose calendar marks the days that have stock minute bars,
 * options and futures, and below it what the chosen day has. Clicking a
 * listed ticker hands it to ``onPick``. */
export function DataDatePicker({ value, onChange, onPick }: {
  value: string;
  onChange: (d: string) => void;
  onPick?: (kind: "stock" | "future", ticker: string) => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [month, setMonth] = useState(monthStart(value || iso(new Date())));
  const [days, setDays] = useState<Days>({});
  const [loading, setLoading] = useState(false);
  const [info, setInfo] = useState<DayInfo | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => { if (value) setMonth(monthStart(value)); }, [value]);

  // availability for the visible month (and its neighbours, for the arrows)
  useEffect(() => {
    const start = addMonths(month, -1);
    const end = iso(new Date(new Date(`${addMonths(month, 2)}T00:00:00Z`).getTime() - 86_400_000));
    setLoading(true);
    fetch(`/api/coverage/days?start=${start}&end=${end}`)
      .then((r) => (r.ok ? r.json() : { days: {} }))
      .then((d: { days: Days }) => setDays((prev) => {
        const out = { ...prev };
        for (const [k, v] of Object.entries(d.days ?? {})) out[k] = Array.from(new Set([...(out[k] ?? []), ...v])).sort();
        return out;
      }))
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, [month]);

  useEffect(() => {
    if (!value) return;
    setInfo(null);
    fetch(`/api/coverage/day?date=${value}`).then((r) => (r.ok ? r.json() : null)).then(setInfo).catch(() => setInfo(null));
  }, [value]);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const sets = useMemo(() => Object.fromEntries(KINDS.map((k) => [k.id, new Set(days[k.id] ?? [])])), [days]);
  const grid = useMemo(() => {
    const first = new Date(`${month}T00:00:00Z`);
    const lead = first.getUTCDay();
    const cells: (string | null)[] = Array(lead).fill(null);
    const d = new Date(first);
    while (d.getUTCMonth() === first.getUTCMonth()) { cells.push(iso(d)); d.setUTCDate(d.getUTCDate() + 1); }
    while (cells.length % 7) cells.push(null);
    return cells;
  }, [month]);
  // jump to the nearest month with data when the current one is empty
  const anyIn = (m: string) => KINDS.some((k) => (days[k.id] ?? []).some((d) => d.startsWith(m.slice(0, 7))));
  const latest = useMemo(() => KINDS.flatMap((k) => days[k.id] ?? []).sort().at(-1), [days]);
  const weekdays = t("Su Mo Tu We Th Fr Sa", "日 一 二 三 四 五 六").split(" ");
  const has = (d: string) => KINDS.filter((k) => sets[k.id]?.has(d));
  const fmtMonth = new Date(`${month}T00:00:00Z`).toLocaleDateString(t("en-US", "zh-CN"), { year: "numeric", month: "long", timeZone: "UTC" });

  return (
    <div className="flex flex-col gap-2" ref={ref}>
      <div className="relative">
        <button type="button" onClick={() => setOpen(!open)}
          className="flex w-full items-center justify-between rounded-md border border-input bg-card px-3 py-2 text-sm text-foreground outline-none focus:border-ring focus:ring-2 focus:ring-ring/20">
          <span className="flex items-center gap-2">
            {value || t("Choose a day", "选择日期")}
            <span className="flex gap-0.5">{value && has(value).map((k) => <span key={k.id} className={cn("h-1.5 w-1.5 rounded-full", k.dot)} />)}</span>
          </span>
          <CalendarDays className="h-4 w-4 text-muted-foreground" />
        </button>
        {open && (
          <div className="absolute left-0 top-11 z-30 w-80 rounded-lg border bg-card p-3 shadow-lg">
            <div className="mb-2 flex items-center justify-between">
              <button type="button" onClick={() => setMonth(addMonths(month, -1))} className="rounded p-1 hover:bg-muted"
                aria-label={t("Previous month", "上个月")}><ChevronLeft className="h-4 w-4" /></button>
              <span className="flex items-center gap-1.5 text-sm font-medium">{fmtMonth}{loading && <Loader2 className="h-3 w-3 animate-spin" />}</span>
              <button type="button" onClick={() => setMonth(addMonths(month, 1))} className="rounded p-1 hover:bg-muted"
                aria-label={t("Next month", "下个月")}><ChevronRight className="h-4 w-4" /></button>
            </div>
            <div className="grid grid-cols-7 gap-0.5 text-center text-[11px] text-muted-foreground">
              {weekdays.map((w) => <div key={w} className="py-1">{w}</div>)}
              {grid.map((d, i) => {
                if (!d) return <div key={`x${i}`} />;
                const kinds = has(d);
                const sel = d === value;
                return (
                  <button type="button" key={d} onClick={() => { onChange(d); setOpen(false); }}
                    className={cn("flex h-10 flex-col items-center justify-center rounded-md text-[13px]",
                      sel ? "bg-primary text-primary-foreground" : kinds.length ? "text-foreground hover:bg-muted" : "text-muted-foreground/50 hover:bg-muted/50")}>
                    {Number(d.slice(8))}
                    <span className="flex h-1.5 gap-0.5">
                      {kinds.map((k) => <span key={k.id} className={cn("h-1 w-1 rounded-full", sel ? "bg-primary-foreground" : k.dot)} />)}
                    </span>
                  </button>
                );
              })}
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 border-t pt-2 text-[11px] text-muted-foreground">
              {KINDS.map((k) => <span key={k.id} className="flex items-center gap-1"><span className={cn("h-1.5 w-1.5 rounded-full", k.dot)} />{t(k.en, k.zh)}</span>)}
              {!anyIn(month) && latest && (
                <button type="button" onClick={() => setMonth(monthStart(latest))} className="ml-auto text-primary hover:underline">
                  {t(`Latest data: ${latest}`, `最近有数据：${latest}`)}
                </button>
              )}
            </div>
          </div>
        )}
      </div>
      {value && (
        <div className="rounded-md border bg-muted/30 px-3 py-2 text-xs">
          {!info ? <span className="text-muted-foreground">{t("Checking this day…", "正在检查这一天的数据…")}</span> : (
            <div className="flex flex-col gap-1.5">
              {KINDS.map((k) => {
                const lv = info.levels[k.id];
                return (
                  <div key={k.id} className="flex flex-wrap items-center gap-1.5">
                    <span className={cn("h-1.5 w-1.5 rounded-full", lv ? k.dot : "bg-muted-foreground/30")} />
                    <span className={lv ? "text-foreground" : "text-muted-foreground"}>{t(k.en, k.zh)}</span>
                    {lv ? (
                      <>
                        <span className="text-muted-foreground">
                          · {lv.tickers} {k.id === "options_minute" ? t("underlyings", "个标的") : t("tickers", "个代码")}
                        </span>
                        {k.id !== "options_minute" && onPick && lv.top.slice(0, 8).map((tk) => (
                          <button type="button" key={tk} onClick={() => onPick(k.id === "futures_minute" ? "future" : "stock", tk)}
                            className="rounded border bg-card px-1.5 font-mono text-[11px] hover:border-ring" title={t("Add", "添加")}>
                            +{tk}
                          </button>
                        ))}
                      </>
                    ) : <span className="text-muted-foreground">· {t("none", "无")}</span>}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
