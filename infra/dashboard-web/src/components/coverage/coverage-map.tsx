"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronDown, ChevronRight, Loader2, Minus, Newspaper, RefreshCw, X } from "lucide-react";

import { useLocale, useT } from "@/components/locale-provider";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

// ── types of /api/coverage/* ──────────────────────────────────────────────

type LevelId = "daily" | "overnight_daily" | "minute" | "quotes" | "options_eod" | "options_minute" | "options_quotes"
  | "futures_daily" | "futures_minute" | "futures_quotes"
  | "crypto_daily" | "crypto_minute" | "fx_daily" | "fx_minute" | "fx_quotes";
type Kind = "stock" | "future" | "crypto" | "fx";
type CellLevels = Partial<Record<LevelId, number>> & { contracts?: number; sessions?: Record<string, number> };
interface Earnings { date: string; time_utc: string; title: string; status?: string; actual_eps?: number | null; estimated_eps?: number | null }
interface Macro { date: string; time_utc: string; title: string; importance?: string; actual?: string | null; consensus?: string | null }
interface Events { news: Record<string, Record<string, number>>; earnings: Record<string, Earnings[]>; macro: Macro[]; notes: string[] }
interface Matrix { tickers: string[]; days: string[]; levels: LevelId[]; cells: Record<string, Record<string, CellLevels>>; events?: Events; kinds?: Record<string, Kind> }
interface Extent { stores: Record<LevelId, { start: string; end: string; days: number } | null>; default: { start: string; end: string }; suggested: { ticker: string }[]; suggested_futures?: string[];
  suggested_crypto?: string[]; suggested_fx?: string[] }
interface CellDetail {
  ticker: string;
  date: string;
  levels: Record<LevelId, { rows: number; contracts?: number; volume?: number; sessions?: Record<string, number> } | null>;
  daily_bar: { open: number; high: number; low: number; close: number; volume: number; settle?: number } | null;
  kind?: Kind;
  minute_span: { first_ns: number; last_ns: number } | null;
  quote_span: { first_ns: number; last_ns: number } | null;
  option_expiries: { expiry: string; contracts: number; volume: number }[];
  corporate_actions: { type: "split" | "dividend"; ratio?: number; cash?: number }[];
  events: { earnings: Earnings[]; macro: Macro[]; news: { id: string; time_utc: string; title: string; publisher?: string; url?: string }[]; notes: string[] };
}

const LEVELS: { id: LevelId; en: string; zh: string; short: string }[] = [
  { id: "daily", en: "Daily bars", zh: "日线", short: "D" },
  { id: "overnight_daily", en: "Overnight daily (Blue Ocean)", zh: "夜盘日线（Blue Ocean）", short: "N" },
  { id: "minute", en: "Minute bars", zh: "分钟线", short: "M" },
  { id: "quotes", en: "Stock quotes", zh: "股票报价", short: "Q" },
  { id: "options_eod", en: "Options EOD", zh: "期权日线", short: "OD" },
  { id: "options_minute", en: "Options minute", zh: "期权分钟成交", short: "OM" },
  { id: "options_quotes", en: "Options quotes", zh: "期权报价", short: "OQ" },
  { id: "futures_daily", en: "Futures daily", zh: "期货日线", short: "FD" },
  { id: "futures_minute", en: "Futures minute", zh: "期货分钟线", short: "FM" },
  { id: "futures_quotes", en: "Futures quotes", zh: "期货报价", short: "FQ" },
  { id: "crypto_daily", en: "Crypto daily", zh: "加密货币日线", short: "CD" },
  { id: "crypto_minute", en: "Crypto minute", zh: "加密货币分钟线", short: "CM" },
  { id: "fx_daily", en: "FX daily", zh: "外汇日线", short: "XD" },
  { id: "fx_minute", en: "FX minute", zh: "外汇分钟线", short: "XM" },
  { id: "fx_quotes", en: "FX quotes (BBO)", zh: "外汇报价（BBO）", short: "XQ" },
];
const SESSIONS = [
  { id: "overnight", en: "Overnight", zh: "夜盘", minutes: 480 },
  { id: "pre", en: "Pre-market", zh: "盘前", minutes: 330 },
  { id: "regular", en: "Regular", zh: "常规", minutes: 390 },
  { id: "post", en: "After-hours", zh: "盘后", minutes: 240 },
] as const;

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
          placeholder={value.length ? "" : t("Add tickers: SPY, /CL (future), X:BTC-USD (crypto), C:EUR-USD (FX)", "添加代码：SPY，期货 /CL，加密货币 X:BTC-USD，外汇 C:EUR-USD")}
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
                <span className="text-xs tabular-nums text-muted-foreground">
                  {s.ticker.startsWith("/") ? t("future", "期货") : s.ticker.startsWith("X:") ? t("crypto", "加密货币")
                    : s.ticker.startsWith("C:") ? t("FX", "外汇") : `$${(s.dollar_volume / 1e6).toFixed(0)}M`}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── the map ───────────────────────────────────────────────────────────────

const STOCK_LEVELS: LevelId[] = ["daily", "overnight_daily", "minute", "quotes"];
const OPTION_LEVELS: LevelId[] = ["options_eod", "options_minute", "options_quotes"];
const FUTURE_LEVELS: LevelId[] = ["futures_daily", "futures_minute", "futures_quotes"];
const CRYPTO_LEVELS: LevelId[] = ["crypto_daily", "crypto_minute"];
const FX_LEVELS: LevelId[] = ["fx_daily", "fx_minute", "fx_quotes"];
const KIND_LEVELS: Record<Kind, LevelId[]> = {
  stock: [...STOCK_LEVELS, ...OPTION_LEVELS], future: FUTURE_LEVELS, crypto: CRYPTO_LEVELS, fx: FX_LEVELS,
};
const MINUTE_LEVELS: LevelId[] = ["minute", "futures_minute", "crypto_minute", "fx_minute"];
const QUOTE_LEVELS: LevelId[] = ["quotes", "futures_quotes", "fx_quotes"];

/** Every calendar day in [start, end]: the map is a continuous time axis. */
function calendar(start: string, end: string): string[] {
  const out: string[] = [];
  for (let d = start; d <= end && out.length < 1200; d = shiftDays(d, 1)) out.push(d);
  return out;
}
const isWeekend = (d: string) => [0, 6].includes(new Date(`${d}T12:00:00Z`).getUTCDay());

type Row =
  | { kind: "group"; key: string; label: string; count: number; group: Kind }
  | { kind: "ticker"; key: string; ticker: string; group: Kind; levels: LevelId[] }
  | { kind: "sub"; key: string; ticker: string; label: string; levels?: LevelId[]; layer?: "news" | "earnings" };

/** The overview of the whole history with a window you drag to pick the range. */
function Brush({ start, end, range, onRange, counts }: {
  start: string; end: string; range: { start: string; end: string };
  onRange: (r: { start: string; end: string }) => void; counts: Record<string, number>;
}) {
  const t = useT();
  const { locale } = useLocale();
  const intl = locale === "zh" ? "zh-CN" : "en-US";
  const ref = React.useRef<HTMLDivElement>(null);
  const days = React.useMemo(() => calendar(start, end), [start, end]);
  const [draft, setDraftState] = React.useState(range);
  const live = React.useRef(range);        // the window as dragged (state lags a render behind)
  const setDraft = (r: { start: string; end: string }) => { live.current = r; setDraftState(r); };
  React.useEffect(() => { live.current = range; setDraftState(range); }, [range]);
  const drag = React.useRef<{ mode: "move" | "l" | "r" | "new"; x0: number; r0: { start: string; end: string };
    moved: boolean } | null>(null);
  const n = Math.max(1, days.length);
  const idx = (d: string) => Math.max(0, Math.min(n - 1, days.indexOf(d) >= 0 ? days.indexOf(d) : (d < start ? 0 : n - 1)));
  const pct = (i: number) => (i / n) * 100;
  const dayAt = (clientX: number) => {
    const r = ref.current!.getBoundingClientRect();
    return Math.max(0, Math.min(n - 1, Math.floor(((clientX - r.left) / r.width) * n)));
  };
  const max = Math.max(1, ...Object.values(counts));

  function down(e: React.PointerEvent, mode: "move" | "l" | "r" | "new") {
    e.preventDefault();
    e.stopPropagation();
    (e.target as Element).setPointerCapture?.(e.pointerId);
    const i = dayAt(e.clientX);
    drag.current = { mode, x0: i, r0: live.current, moved: false };
  }
  function move(e: React.PointerEvent) {
    const g = drag.current;
    if (!g) return;
    const i = dayAt(e.clientX);
    if (i !== g.x0) g.moved = true;
    const a = idx(g.r0.start), b = idx(g.r0.end);
    if (g.mode === "new" && !g.moved) return;
    if (g.mode === "move") {
      const w = b - a;
      const s = Math.max(0, Math.min(n - 1 - w, a + i - g.x0));
      setDraft({ start: days[s], end: days[s + w] });
    } else if (g.mode === "l") setDraft({ start: days[Math.min(i, b)], end: g.r0.end });
    else if (g.mode === "r") setDraft({ start: g.r0.start, end: days[Math.max(i, a)] });
    else setDraft({ start: days[Math.min(i, g.x0)], end: days[Math.max(i, g.x0)] });
  }
  function up(e?: React.PointerEvent) {
    if (!drag.current) return;
    if (e) move(e);
    const g = drag.current;
    if (g.mode === "new" && !g.moved) {           // a click: centre the window there
      const w = idx(g.r0.end) - idx(g.r0.start);
      const s0 = Math.max(0, Math.min(n - 1 - w, g.x0 - Math.floor(w / 2)));
      setDraft({ start: days[s0], end: days[s0 + w] });
    }
    drag.current = null;
    const r = live.current;
    if (r.start !== range.start || r.end !== range.end) onRange(r);
  }
  const a = idx(draft.start), b = idx(draft.end);
  const months = days.map((d, i) => (i === 0 || d.slice(8) === "01" ? i : -1)).filter((i) => i >= 0);

  return (
    <div className="select-none">
      <div className="mb-1 flex items-center justify-between text-[11px] text-muted-foreground">
        <span>{t("Drag the window to move through the history; drag its edges to resize.", "拖动窗口浏览历史，拖动边缘调整范围。")}</span>
        <span className="tabular-nums text-foreground">{draft.start} → {draft.end} · {b - a + 1} {t("days", "天")}</span>
      </div>
      <div ref={ref} className="relative h-12 cursor-crosshair rounded-md border bg-muted/40"
        onPointerDown={(e) => down(e, "new")} onPointerMove={move} onPointerUp={up} onPointerLeave={() => up()}>
        <svg className="absolute inset-0 h-full w-full" preserveAspectRatio="none" viewBox={`0 0 ${n} 100`}>
          {days.map((d, i) => counts[d] ? (
            <rect key={d} x={i} width={1} y={100 - (counts[d] / max) * 90} height={(counts[d] / max) * 90}
              fill="hsl(var(--primary) / 0.45)" />
          ) : null)}
        </svg>
        {months.map((i) => (
          <span key={i} className="pointer-events-none absolute top-0 h-full border-l border-border/70" style={{ left: `${pct(i)}%` }}>
            {(days[i].slice(5, 7) === "01" || months.length < 18) && (
              <span className="absolute left-0.5 top-0 whitespace-nowrap text-[9px] text-muted-foreground">
                {new Intl.DateTimeFormat(intl, { year: "2-digit", month: "short" }).format(new Date(`${days[i]}T12:00:00Z`))}
              </span>
            )}
          </span>
        ))}
        <div className="absolute top-0 h-full cursor-grab rounded-sm border-2 border-primary bg-primary/10 active:cursor-grabbing"
          style={{ left: `${pct(a)}%`, width: `${Math.max(0.6, pct(b - a + 1))}%` }}
          onPointerDown={(e) => down(e, "move")}>
          <span className="absolute -left-1 top-0 h-full w-2 cursor-ew-resize" onPointerDown={(e) => down(e, "l")} />
          <span className="absolute -right-1 top-0 h-full w-2 cursor-ew-resize" onPointerDown={(e) => down(e, "r")} />
        </div>
      </div>
    </div>
  );
}

/** One asset over the selected range: levels, closes and related series. */
function AssetPanel({ ticker, range, onClose, onAdd }: {
  ticker: string; range: { start: string; end: string }; onClose: () => void; onAdd: (t: string) => void;
}) {
  const t = useT();
  const { locale } = useLocale();
  const L = (x: { en: string; zh: string }) => (locale === "zh" ? x.zh : x.en);
  const q = useQuery({
    queryKey: ["coverage", "asset", ticker, range.start, range.end],
    queryFn: () => getJson<{
      ticker: string; kind: Kind; levels: Record<LevelId, { first: string; last: string; days: number } | null>;
      series: { date: string; close: number | null; volume: number }[]; related: string[];
    }>(`/api/coverage/asset?ticker=${encodeURIComponent(ticker)}&start=${range.start}&end=${range.end}`),
  });
  const a = q.data;
  const pts = (a?.series ?? []).filter((p) => p.close != null);
  const lo = Math.min(...pts.map((p) => p.close as number)), hi = Math.max(...pts.map((p) => p.close as number));
  const span = calendar(range.start, range.end);
  const x = (d: string) => (Math.max(0, span.indexOf(d)) / Math.max(1, span.length - 1)) * 100;
  const y = (v: number) => 90 - ((v - lo) / Math.max(1e-9, hi - lo)) * 80;
  const shown = a ? LEVELS.filter((lv) => KIND_LEVELS[a.kind].includes(lv.id)) : [];
  return (
    <aside className="fixed bottom-0 right-0 top-12 z-30 flex w-full max-w-lg flex-col border-l bg-card" aria-label={t("Asset", "资产")}>
      <div className="flex items-start justify-between border-b px-4 py-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-base font-semibold">{ticker}</span>
            {a && <Badge variant="secondary">{({ stock: t("Stock", "股票"), future: t("Future", "期货"), crypto: t("Crypto", "加密货币"), fx: t("FX", "外汇") })[a.kind]}</Badge>}
          </div>
          <div className="text-xs text-muted-foreground">{range.start} → {range.end}</div>
        </div>
        <button onClick={onClose} className="rounded-md p-1 text-muted-foreground hover:bg-accent" aria-label={t("Close", "关闭")}><X className="h-4 w-4" /></button>
      </div>
      <div className="flex-1 space-y-5 overflow-y-auto p-4 text-[13px]">
        {q.isLoading && <div className="flex items-center gap-2 text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> {t("Loading…", "加载中…")}</div>}
        {q.isError && <Alert variant="error">{(q.error as Error).message}</Alert>}
        {a && (
          <>
            <section>
              <h3 className="mb-2 text-xs font-semibold text-muted-foreground">
                {a.kind === "future" ? t("Daily settle", "每日结算价") : t("Daily close", "每日收盘价")}
              </h3>
              {pts.length > 1 ? (
                <div className="rounded-md border p-2">
                  <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="h-36 w-full">
                    <polyline fill="none" stroke="hsl(var(--primary))" strokeWidth={0.6} vectorEffect="non-scaling-stroke"
                      points={pts.map((p) => `${x(p.date)},${y(p.close as number)}`).join(" ")} />
                    {pts.map((p) => <circle key={p.date} cx={x(p.date)} cy={y(p.close as number)} r={0.7} fill="hsl(var(--primary))" />)}
                  </svg>
                  <div className="mt-1 flex justify-between text-[11px] tabular-nums text-muted-foreground">
                    <span>{pts[0].date} · {pts[0].close}</span><span>{lo.toFixed(2)} – {hi.toFixed(2)}</span>
                    <span>{pts.at(-1)!.date} · {pts.at(-1)!.close}</span>
                  </div>
                </div>
              ) : <p className="text-muted-foreground">{t("No daily bars in this range.", "此区间没有日线。")}</p>}
            </section>
            <section>
              <h3 className="mb-2 text-xs font-semibold text-muted-foreground">{t("Data levels in this range", "此区间的数据层")}</h3>
              <table className="w-full text-xs">
                <thead className="text-muted-foreground">
                  <tr><th className="py-1 text-left font-medium">{t("Level", "数据层")}</th><th className="text-right font-medium">{t("Days", "天数")}</th>
                    <th className="text-right font-medium">{t("First", "最早")}</th><th className="text-right font-medium">{t("Last", "最晚")}</th></tr>
                </thead>
                <tbody>
                  {shown.map((lv) => {
                    const v = a.levels[lv.id];
                    return (
                      <tr key={lv.id} className="border-t">
                        <td className="py-1.5">{v ? <Check className="mr-1 inline h-3.5 w-3.5 text-success" /> : <Minus className="mr-1 inline h-3.5 w-3.5 text-muted-foreground/60" />}{L(lv)}</td>
                        <td className="text-right tabular-nums">{v?.days ?? "—"}</td>
                        <td className="text-right font-mono">{v?.first ?? ""}</td>
                        <td className="text-right font-mono">{v?.last ?? ""}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </section>
            {a.related.length > 0 && (
              <section>
                <h3 className="mb-2 text-xs font-semibold text-muted-foreground">{t("Other series of this product", "同一品种的其他序列")}</h3>
                <div className="flex flex-wrap gap-1">
                  {a.related.map((r) => (
                    <button key={r} onClick={() => onAdd(r)} className="rounded border px-2 py-0.5 font-mono text-xs hover:border-ring">+{r}</button>
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </div>
    </aside>
  );
}

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
  const [assetOf, setAssetOf] = React.useState<string | null>(null);
  const [open, setOpen] = React.useState<Set<string>>(new Set());
  const [folded, setFolded] = React.useState<Set<string>>(new Set());

  React.useEffect(() => {
    if (!extent.data) return;
    if (!range) setRange(extent.data.default);
    if (!tickers.length) setTickers([...extent.data.suggested.map((s) => s.ticker).slice(0, 10),
      ...(extent.data.suggested_futures ?? []).slice(0, 6), ...(extent.data.suggested_crypto ?? []).slice(0, 3),
      ...(extent.data.suggested_fx ?? []).slice(0, 3)]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [extent.data]);

  // the whole history, for the brush
  const full = React.useMemo(() => {
    const ranges = Object.values(extent.data?.stores ?? {}).filter(Boolean) as { start: string; end: string }[];
    if (!ranges.length) return null;
    return { start: ranges.map((r) => r.start).sort()[0], end: ranges.map((r) => r.end).sort().at(-1)! };
  }, [extent.data]);
  const overview = useQuery({
    queryKey: ["coverage", "days", full?.start, full?.end],
    queryFn: () => getJson<{ days: Record<string, string[]> }>(`/api/coverage/days?start=${full!.start}&end=${full!.end}`),
    enabled: Boolean(full),
    staleTime: 300_000,
  });
  const counts = React.useMemo(() => {
    const m: Record<string, number> = {};
    for (const ds of Object.values(overview.data?.days ?? {})) for (const d of ds) m[d] = (m[d] ?? 0) + 1;
    return m;
  }, [overview.data]);

  const ready = Boolean(range && tickers.length);
  const matrix = useQuery({
    queryKey: ["coverage", "matrix", tickers.join(","), range?.start, range?.end],
    queryFn: () => getJson<Matrix>(`/api/coverage/matrix?tickers=${encodeURIComponent(tickers.join(","))}&start=${range!.start}&end=${range!.end}`),
    enabled: ready,
    staleTime: 60_000,
    placeholderData: (prev) => prev,
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
  const days = React.useMemo(() => (range ? calendar(range.start, range.end) : []), [range]);
  const LABEL = 128;
  const raw = days.length ? Math.floor((width - LABEL) / days.length) : 16;
  const gap = raw >= 9 ? 2 : raw >= 5 ? 1 : 0;
  const W = Math.max(3, Math.min(24, raw - gap));
  const cols = `${LABEL}px repeat(${days.length}, ${W}px)`;
  const monthStart = (i: number) => {
    if (i > 0 && days[i].slice(0, 7) === days[i - 1].slice(0, 7)) return false;
    let run = 0;
    while (i + run < days.length && days[i + run].slice(0, 7) === days[i].slice(0, 7)) run += 1;
    return run * (W + gap) >= 56 || i + run === days.length;
  };

  const data = matrix.data;
  const maxRows = React.useMemo(() => {
    const m: Partial<Record<LevelId, number>> = {};
    for (const row of Object.values(data?.cells ?? {}))
      for (const c of Object.values(row)) for (const lv of LEVELS) m[lv.id] = Math.max(m[lv.id] ?? 0, c[lv.id] ?? 0);
    return m;
  }, [data]);
  const macroByDay = React.useMemo(() => {
    const m: Record<string, Macro[]> = {};
    for (const e of data?.events?.macro ?? []) (m[e.date] ??= []).push(e);
    return m;
  }, [data]);
  const earnByKey = React.useMemo(() => {
    const m: Record<string, Earnings> = {};
    for (const [tk, list] of Object.entries(data?.events?.earnings ?? {})) for (const e of list) m[`${tk}|${e.date}`] = e;
    return m;
  }, [data]);
  const maxNews = React.useMemo(() => Math.max(1, ...Object.values(data?.events?.news ?? {}).flatMap((r) => Object.values(r))), [data]);

  const rows: Row[] = React.useMemo(() => {
    if (!data) return [];
    const of = (k: Kind) => data.tickers.filter((tk) => (data.kinds?.[tk] ?? "stock") === k);
    const out: Row[] = [];
    const group = (g: Kind, list: string[], label: string) => {
      if (!list.length) return;
      out.push({ kind: "group", key: `g-${g}`, label, count: list.length, group: g });
      if (folded.has(g)) return;
      for (const tk of list) {
        const levels = KIND_LEVELS[g];
        out.push({ kind: "ticker", key: tk, ticker: tk, group: g, levels });
        if (!open.has(tk)) continue;
        if (g === "stock") {
          out.push({ kind: "sub", key: `${tk}-px`, ticker: tk, label: t("Stock data", "股票行情"), levels: STOCK_LEVELS });
          out.push({ kind: "sub", key: `${tk}-opt`, ticker: tk, label: t("Options", "期权"), levels: OPTION_LEVELS });
          if (show.news) out.push({ kind: "sub", key: `${tk}-news`, ticker: tk, label: t("News", "新闻"), layer: "news" });
          if (show.earnings) out.push({ kind: "sub", key: `${tk}-earn`, ticker: tk, label: t("Company events", "公司事件"), layer: "earnings" });
        } else {
          for (const lv of KIND_LEVELS[g]) {
            const meta = LEVELS.find((x) => x.id === lv)!;
            out.push({ kind: "sub", key: `${tk}-${lv}`, ticker: tk, label: L(meta), levels: [lv] });
          }
        }
      }
    };
    group("stock", of("stock"), t("Stocks", "个股"));
    group("future", of("future"), t("Futures", "期货"));
    group("crypto", of("crypto"), t("Crypto", "加密货币"));
    group("fx", of("fx"), t("FX", "外汇"));
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, open, folded, show.news, show.earnings, locale]);

  function shade(c: CellLevels | undefined, levels: LevelId[], d: string): React.CSSProperties {
    const empty = { background: isWeekend(d) ? "transparent" : "hsl(var(--muted) / 0.7)" };
    if (!c) return empty;
    if (color !== "all") {
      if (!levels.includes(color)) return empty;
      const v = c[color] ?? 0;
      if (!v) return empty;
      return { background: `hsl(var(--primary) / ${(0.3 + 0.7 * (Math.log1p(v) / Math.log1p(maxRows[color] ?? v))).toFixed(2)})` };
    }
    const n = levels.filter((lv) => (c[lv] ?? 0) > 0).length;
    if (!n) return empty;
    return { background: `hsl(var(--primary) / ${(0.18 + 0.82 * (n / levels.length)).toFixed(2)})` };
  }

  function cellTitle(tk: string, d: string, c: CellLevels | undefined, levels: LevelId[], news: number, earn?: Earnings) {
    const parts = LEVELS.filter((lv) => levels.includes(lv.id) && (c?.[lv.id] ?? 0) > 0).map((lv) =>
      lv.id === "options_eod" && c?.contracts ? `${L(lv)} (${c.contracts} ${t("contracts", "个合约")})` :
      MINUTE_LEVELS.includes(lv.id) ? `${L(lv)} (${c?.[lv.id]})` : L(lv));
    const lines = [`${tk} · ${d}`, parts.length ? parts.join(", ") : t("no data", "无数据")];
    if (news) lines.push(t(`${news} news`, `${news} 条新闻`));
    if (earn) lines.push(`${t("Earnings", "财报")}: ${earn.title}`);
    return lines.join("\n");
  }

  const preset = (n: number) => {
    const end = full?.end ?? range?.end;
    if (end) setRange({ start: shiftDays(end, -n), end });
  };
  const toggle = (set: Set<string>, k: string, f: (s: Set<string>) => void) => {
    const s = new Set(set);
    if (s.has(k)) s.delete(k); else s.add(k);
    f(s);
  };
  const H = Math.max(12, Math.min(20, W + 4));

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="grid gap-3 p-4 lg:grid-cols-[1fr_auto]">
          <TickerInput value={tickers} onChange={setTickers} />
          <div className="flex flex-wrap items-center gap-2">
            <input type="date" value={range?.start ?? ""} max={range?.end}
              onChange={(e) => range && e.target.value && setRange({ ...range, start: e.target.value })}
              className="h-9 rounded-md border border-input bg-card px-2 text-[13px]" aria-label={t("Start", "开始")} />
            <span className="text-muted-foreground">–</span>
            <input type="date" value={range?.end ?? ""} min={range?.start}
              onChange={(e) => range && e.target.value && setRange({ ...range, end: e.target.value })}
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
                <option value="all">{t("Share of the row's levels", "该行数据层的覆盖比例")}</option>
                {LEVELS.map((lv) => <option key={lv.id} value={lv.id}>{L(lv)}</option>)}
              </select>
            </label>
            <span className="text-muted-foreground">{t("Layers", "图层")}</span>
            {([["news", t("News", "新闻")], ["earnings", t("Company events", "公司事件")], ["macro", t("Macro", "宏观")]] as const).map(([k, label]) => (
              <label key={k} className="flex items-center gap-1.5">
                <input type="checkbox" checked={show[k]} onChange={(e) => setShow({ ...show, [k]: e.target.checked })} />
                {label}
              </label>
            ))}
            <button onClick={() => setOpen(new Set(open.size ? [] : tickers))} className="ml-auto text-xs text-muted-foreground hover:text-foreground">
              {open.size ? t("Collapse all", "全部收起") : t("Expand all", "全部展开")}
            </button>
          </div>
        </CardContent>
      </Card>

      {extent.isError && <Alert variant="error" title={t("Coverage is unavailable", "覆盖信息不可用")}>{(extent.error as Error).message}</Alert>}
      {matrix.isError && <Alert variant="error" title={t("Could not load the map", "无法加载覆盖图")}>{(matrix.error as Error).message}</Alert>}
      {(data?.events?.notes?.length ?? 0) > 0 && (
        <Alert variant="warning">{t("Some events are missing: ", "部分事件缺失：")}{data!.events!.notes.join("; ")}</Alert>
      )}

      <Card>
        <CardContent className="space-y-4 p-4">
          <div ref={wrap} className="relative overflow-x-auto">
            {data && matrix.isFetching && (
              <div className="absolute right-2 top-0 z-10 flex items-center gap-1.5 rounded-md bg-card/90 px-2 py-1 text-[11px] text-muted-foreground shadow-sm">
                <Loader2 className="h-3 w-3 animate-spin" /> {t("Reading partitions…", "正在读取分区…")}
              </div>
            )}
            {!data && ready && (
              <div className="flex h-40 items-center justify-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" /> {t("Reading partitions…", "正在读取分区…")}
              </div>
            )}
            {data && (
              <div className={cn("inline-block min-w-full select-none text-[11px] transition-opacity", matrix.isFetching && "opacity-60")}
                role="grid" aria-label={t("Data coverage", "数据覆盖")}>
                {/* month row */}
                <div className="grid" style={{ gridTemplateColumns: cols, columnGap: gap }}>
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
                {/* day row: Mondays (or the 1st when columns are narrow) */}
                <div className="grid border-b pb-1" style={{ gridTemplateColumns: cols, columnGap: gap }}>
                  <div />
                  {days.map((d) => {
                    const dow = new Date(`${d}T12:00:00Z`).getUTCDay();
                    const label = W >= 9 ? dow === 1 : d.slice(8) === "15";
                    return (
                      <div key={d} className="relative h-4 text-muted-foreground">
                        {label && <span className="absolute left-0 tabular-nums">{Number(d.slice(8))}</span>}
                      </div>
                    );
                  })}
                </div>
                {/* macro lane */}
                {show.macro && (
                  <div className="grid items-center border-b py-1" style={{ gridTemplateColumns: cols, columnGap: gap }}>
                    <div className="truncate pr-2 font-medium text-muted-foreground">{t("Macro releases", "宏观数据")}</div>
                    {days.map((d) => {
                      const ev = macroByDay[d];
                      const high = ev?.some((e) => e.importance === "high");
                      return (
                        <div key={d} className="flex h-4 items-center justify-center" title={ev?.map((e) => `${etTime(e.time_utc, intl)} ET  ${e.title}${e.actual ? ` = ${e.actual}` : ""}`).join("\n")}>
                          {ev && <span className={cn("rotate-45 border border-warning", W >= 6 ? "h-2 w-2" : "h-1.5 w-1.5", high && "bg-warning")} />}
                        </div>
                      );
                    })}
                  </div>
                )}
                {/* groups and rows */}
                <div className="mt-1 space-y-[2px]">
                  {rows.map((r) => {
                    if (r.kind === "group") {
                      return (
                        <button key={r.key} onClick={() => toggle(folded, r.group, setFolded)}
                          className="flex w-full items-center gap-1 pb-0.5 pt-2 text-left text-xs font-semibold text-foreground">
                          {folded.has(r.group) ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                          {r.label} <span className="font-normal text-muted-foreground">· {r.count}</span>
                        </button>
                      );
                    }
                    const tk = r.ticker;
                    const expanded = open.has(tk);
                    const isLayer = r.kind === "sub" && r.layer;
                    return (
                      <div key={r.key} className="grid items-center" style={{ gridTemplateColumns: cols, columnGap: gap }} role="row">
                        {r.kind === "ticker" ? (
                          <div className="flex min-w-0 items-center gap-0.5 pr-2">
                            <button onClick={() => toggle(open, tk, setOpen)} className="rounded p-0.5 text-muted-foreground hover:text-foreground"
                              aria-label={expanded ? t("Collapse", "收起") : t("Expand", "展开")}>
                              {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                            </button>
                            <button onClick={() => setAssetOf(tk)} title={t(`${tk}: asset details`, `${tk}：资产详情`)}
                              className="truncate font-mono text-xs font-medium hover:text-primary hover:underline">{tk}</button>
                          </div>
                        ) : (
                          <div className="truncate pl-6 pr-2 text-muted-foreground">{r.label}</div>
                        )}
                        {days.map((d) => {
                          const c = data.cells[tk]?.[d];
                          const news = data.events?.news?.[tk]?.[d] ?? 0;
                          const earn = earnByKey[`${tk}|${d}`];
                          if (isLayer) {
                            const val = r.layer === "news" ? news : earn ? 1 : 0;
                            return (
                              <div key={d} style={{ height: H - 4 }} className="flex items-center justify-center"
                                title={r.layer === "news" ? (news ? t(`${news} news`, `${news} 条新闻`) : "") : earn?.title}>
                                {r.layer === "news" && val > 0 && (
                                  <span className="w-full rounded-[2px]" style={{
                                    height: Math.max(2, ((H - 4) * Math.min(1, val / maxNews))),
                                    background: "hsl(var(--chart-4) / 0.8)" }} />
                                )}
                                {r.layer === "earnings" && earn && <span className="h-2 w-2 rounded-full bg-warning" />}
                              </div>
                            );
                          }
                          const levels = r.levels!;
                          const on = selected?.ticker === tk && selected.date === d;
                          const marks = r.kind === "ticker" && !expanded;
                          return (
                            <button key={d} role="gridcell" onClick={() => setSelected(on ? null : { ticker: tk, date: d })}
                              title={cellTitle(tk, d, c, levels, news, earn)}
                              style={{ ...shade(c, levels, d), height: r.kind === "ticker" ? H : H - 4 }}
                              className={cn("relative rounded-[2px] hover:outline hover:outline-1 hover:outline-foreground/50",
                                on && "outline outline-2 outline-foreground")}>
                              {marks && show.earnings && earn && <span className="absolute -right-0.5 -top-0.5 h-1.5 w-1.5 rounded-full border border-card bg-warning" />}
                              {marks && show.news && news > 0 && (
                                <span className="absolute inset-x-0 bottom-0 h-[2px]" style={{ background: `hsl(var(--chart-4) / ${Math.min(1, 0.35 + news * 0.15)})` }} />
                              )}
                            </button>
                          );
                        })}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>

          {full && range && (
            <Brush start={full.start} end={full.end} range={range} onRange={setRange} counts={counts} />
          )}

          {/* legend */}
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t pt-3 text-xs text-muted-foreground">
            {color === "all" ? (
              <span className="flex items-center gap-1.5">
                {t("Levels present in the row", "该行已有的数据层")}
                {[0, 0.18, 0.45, 0.73, 1].map((a, i) => (
                  <span key={i} className="h-3 w-4 rounded-[2px]" style={{ background: i ? `hsl(var(--primary) / ${a})` : "hsl(var(--muted))" }} />
                ))}
                <span>{t("none → all", "无 → 全部")}</span>
              </span>
            ) : (
              <span className="flex items-center gap-1.5">
                {L(LEVELS.find((lv) => lv.id === color)!)}
                <span className="h-3 w-4 rounded-[2px] bg-muted" /> {t("none", "无")}
                <span className="h-3 w-4 rounded-[2px]" style={{ background: "hsl(var(--primary) / 0.35)" }} />
                <span className="h-3 w-4 rounded-[2px]" style={{ background: "hsl(var(--primary))" }} /> {t("more rows", "行数更多")}
              </span>
            )}
            <span className="flex items-center gap-1.5"><span className="h-3 w-4 rounded-[2px] border border-dashed" /> {t("weekend", "周末")}</span>
            <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-warning" /> {t("earnings", "财报")}</span>
            <span className="flex items-center gap-1.5"><span className="h-[3px] w-4 rounded-full" style={{ background: "hsl(var(--chart-4))" }} /> {t("news", "新闻")}</span>
            <span className="flex items-center gap-1.5"><span className="h-2 w-2 rotate-45 bg-warning" /> {t("macro release", "宏观数据发布")}</span>
            <span className="ml-auto">{t("Click a ticker for the asset, a cell for the day; ▸ shows the layers.", "点击代码查看资产，点击单元格查看当天；▸ 展开分层。")}</span>
          </div>
        </CardContent>
      </Card>

      {selected && <CellPanel ticker={selected.ticker} date={selected.date} onClose={() => setSelected(null)} />}
      {assetOf && range && (
        <AssetPanel ticker={assetOf} range={range} onClose={() => setAssetOf(null)}
          onAdd={(x) => setTickers((cur) => (cur.includes(x) ? cur : [...cur, x]))} />
      )}
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
                {c.daily_bar.settle != null && (
                  <div className="col-span-5 text-[11px] text-muted-foreground">{t("Settle", "结算价")} <span className="font-medium text-foreground">{c.daily_bar.settle}</span></div>
                )}
              </div>
            )}

            <section>
              <h3 className="mb-2 text-xs font-semibold text-muted-foreground">{t("Data levels", "数据层")}</h3>
              <ul className="divide-y rounded-md border">
                {LEVELS.filter((lv) => KIND_LEVELS[c.kind ?? "stock"].includes(lv.id)).map((lv) => {
                  const info = c.levels[lv.id];
                  const span = MINUTE_LEVELS.includes(lv.id) ? c.minute_span : QUOTE_LEVELS.includes(lv.id) ? c.quote_span : null;
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
