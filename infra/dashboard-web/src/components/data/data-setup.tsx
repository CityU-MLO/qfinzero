"use client";

import * as React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowUp, CheckCircle2, ChevronRight, CloudDownload, File, Folder, FolderInput, HardDrive, KeyRound, Loader2,
  RefreshCw, Search, X,
} from "lucide-react";

import { StorageStatus } from "@/components/data/storage-status";
import { useLocale, useT } from "@/components/locale-provider";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Segmented } from "@/components/ui/segmented";
import {
  QUOTE_INTERVALS, dataAdmin, type BrowseEntry, type DownloadQuote, type InspectResult, type Job, type QuoteIntervals, type Vendor,
} from "@/lib/data-admin";
import { cn } from "@/lib/utils";

const inputCls =
  "h-9 w-full rounded-md border border-input bg-card px-2.5 text-[13px] outline-none focus:border-ring focus:ring-2 focus:ring-ring/20";

const HINT: Record<string, [string, string]> = {
  dbn: ["DBN", "DBN"],
  "dated-parquet": ["massive parquet", "massive parquet"],
  "massive-csv": ["massive csv.gz", "massive csv.gz"],
  parquet: ["parquet", "parquet"],
  massive: ["massive", "massive"],
  databento: ["Databento dataset", "Databento 数据集"],
};

const DATABENTO_DATASETS = ["EQUS.MINI", "EQUS.SUMMARY", "XNAS.ITCH", "DBEQ.BASIC", "XNYS.PILLAR", "ARCX.PILLAR", "OPRA.PILLAR", "OCEA.MEMOIR"];
const DATABENTO_SCHEMAS = ["ohlcv-1m", "ohlcv-1s", "ohlcv-1h", "ohlcv-1d", "ohlcv-eod", "trades", "tbbo", "tcbbo", "cmbp-1", "cbbo-1s", "cbbo-1m", "bbo-1s", "bbo-1m", "mbp-1", "mbo"];

function bytes(n?: number | null): string {
  if (n == null) return "";
  if (n < 1024) return `${n} B`;
  const u = ["KB", "MB", "GB", "TB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(v < 10 ? 1 : 0)} ${u[i]}`;
}

// ── file browser ──────────────────────────────────────────────────────────

function FileBrowser({ selected, onToggle }: { selected: string[]; onToggle: (path: string) => void }) {
  const t = useT();
  const { locale } = useLocale();
  const [path, setPath] = React.useState<string | null>(null);
  const [filter, setFilter] = React.useState("");
  const q = useQuery({ queryKey: ["setup", "browse", path], queryFn: () => dataAdmin.browse(path) });
  const entries = (q.data?.entries ?? []).filter((e) => !filter || e.name.toLowerCase().includes(filter.toLowerCase()));
  const root = q.data?.roots.find((r) => path && (path === r || path.startsWith(`${r}/`)));
  const crumbs = path && root ? [root, ...path.slice(root.length).split("/").filter(Boolean)] : [];

  const go = (e: BrowseEntry) => e.dir && (setPath(e.path), setFilter(""));

  return (
    <Card className="flex min-h-[460px] flex-col">
      <div className="flex flex-wrap items-center gap-1 border-b px-3 py-2 text-[13px]">
        <button onClick={() => setPath(null)} className="flex items-center gap-1 rounded-md px-1.5 py-1 text-muted-foreground hover:bg-accent hover:text-foreground">
          <HardDrive className="h-3.5 w-3.5" /> {t("Roots", "根目录")}
        </button>
        {crumbs.map((c, i) => {
          const full = i === 0 ? c : `${crumbs[0]}/${crumbs.slice(1, i + 1).join("/")}`;
          return (
            <React.Fragment key={full}>
              <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
              <button onClick={() => setPath(full)} className="max-w-[16rem] truncate rounded-md px-1.5 py-1 font-mono hover:bg-accent">{c}</button>
            </React.Fragment>
          );
        })}
        <div className="ml-auto flex items-center gap-1">
          {q.data?.parent && (
            <Button size="icon" variant="ghost" onClick={() => setPath(q.data!.parent)} title={t("Up", "上一级")}><ArrowUp /></Button>
          )}
          <Button size="icon" variant="ghost" onClick={() => q.refetch()} title={t("Refresh", "刷新")}>
            <RefreshCw className={q.isFetching ? "animate-spin" : ""} />
          </Button>
        </div>
      </div>
      <div className="flex items-center gap-2 border-b px-3 py-2">
        <label className="relative flex-1">
          <Search className="pointer-events-none absolute left-2 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={t("Filter this folder", "筛选当前目录")}
            className="h-8 w-full rounded-md border border-input bg-card pl-7 pr-2 text-[13px] outline-none focus:border-ring" />
        </label>
        {path && (
          <Button size="sm" variant={selected.includes(path) ? "secondary" : "outline"} onClick={() => onToggle(path)}>
            <FolderInput /> {selected.includes(path) ? t("Folder selected", "已选此目录") : t("Select this folder", "选择此目录")}
          </Button>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {q.isLoading && <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> {t("Loading…", "加载中…")}</div>}
        {q.isError && <div className="p-3"><Alert variant="error">{(q.error as Error).message}</Alert></div>}
        <table className="w-full text-[13px]">
          <tbody>
            {entries.map((e) => {
              const on = selected.includes(e.path);
              return (
                <tr key={e.path} className={cn("border-b last:border-0 hover:bg-muted/40", on && "bg-primary/5")}>
                  <td className="w-8 py-1.5 pl-3">
                    {path && <input type="checkbox" checked={on} onChange={() => onToggle(e.path)} aria-label={e.name} />}
                  </td>
                  <td className="py-1.5">
                    <button onClick={() => (e.dir ? go(e) : onToggle(e.path))} className="flex items-center gap-2 text-left">
                      {e.dir ? <Folder className="h-4 w-4 shrink-0 text-primary" /> : <File className="h-4 w-4 shrink-0 text-muted-foreground" />}
                      <span className={cn("break-all font-mono", e.dir && "font-medium")}>{e.name}</span>
                    </button>
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    {e.hint && HINT[e.hint] && <Badge variant="secondary">{locale === "zh" ? HINT[e.hint][1] : HINT[e.hint][0]}</Badge>}
                  </td>
                  <td className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums text-muted-foreground">{e.dir ? "" : bytes(e.size)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {q.data?.truncated && <p className="p-3 text-xs text-muted-foreground">{t("Only the first 3,000 entries are shown; use the filter.", "只显示前 3000 项，请使用筛选。")}</p>}
        {q.data && !entries.length && <p className="p-4 text-sm text-muted-foreground">{t("Empty folder.", "空目录。")}</p>}
      </div>
    </Card>
  );
}

// ── BBO sampling ──────────────────────────────────────────────────────────

function IntervalPicker({ value, onChange }: { value: QuoteIntervals; onChange: (v: QuoteIntervals) => void }) {
  const t = useT();
  const sel = (asset: keyof QuoteIntervals, label: string) => (
    <label className="flex items-center gap-1.5">
      {label}
      <select value={value[asset] ?? 1} onChange={(e) => onChange({ ...value, [asset]: Number(e.target.value) })}
        className="h-8 rounded-md border border-input bg-card px-2">
        {QUOTE_INTERVALS.map((m) => <option key={m} value={m}>{m === 1 ? t("every minute", "每分钟") : t(`every ${m} min`, `每 ${m} 分钟`)}</option>)}
      </select>
    </label>
  );
  return (
    <div className="flex flex-wrap items-center gap-3 text-[13px]" title={t(
      "One NBBO per interval is kept in the quote stores; readers carry it forward. Applies to this and later conversions.",
      "报价存储中每个时间间隔保留一条 NBBO，读取时沿用上一条。对本次及之后的转换生效。")}>
      <span className="text-muted-foreground">{t("BBO sampling", "BBO 采样")}</span>
      {sel("stock", t("stocks", "股票"))}
      {sel("option", t("options", "期权"))}
      {sel("future", t("futures", "期货"))}
    </div>
  );
}

// ── selection, inspection and import ─────────────────────────────────────

function ImportPanel({ vendor, selected, intervals, onRemove, onClear, onJob }: {
  vendor: Vendor; selected: string[]; intervals: QuoteIntervals; onRemove: (p: string) => void; onClear: () => void; onJob: (j: Job) => void;
}) {
  const [iv, setIv] = React.useState<QuoteIntervals>(intervals);
  React.useEffect(() => setIv(intervals), [intervals]);
  const t = useT();
  const [info, setInfo] = React.useState<InspectResult | null>(null);
  const [busy, setBusy] = React.useState<"" | "inspect" | "import">("");
  const [error, setError] = React.useState("");
  const [convert, setConvert] = React.useState(true);
  const [jobs, setJobs] = React.useState(4);
  React.useEffect(() => setInfo(null), [selected, vendor]);

  const run = async (what: "inspect" | "import") => {
    setBusy(what);
    setError("");
    try {
      if (what === "inspect") setInfo(await dataAdmin.inspect(vendor, selected));
      else onJob(await dataAdmin.importLocal(vendor, selected, convert, jobs, iv));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  return (
    <Card className="flex flex-col">
      <CardHeader>
        <CardTitle>{t("Selection", "已选内容")}</CardTitle>
        <CardDescription>
          {t("Folders or files to bring in. Files are linked into the raw library, not copied.", "要导入的目录或文件。文件以链接方式加入原始数据库，不会复制。")}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {selected.length === 0 ? (
          <p className="rounded-md border border-dashed px-3 py-6 text-center text-[13px] text-muted-foreground">
            {t("Tick folders or files in the browser.", "在左侧浏览器中勾选目录或文件。")}
          </p>
        ) : (
          <ul className="max-h-40 space-y-1 overflow-auto">
            {selected.map((p) => (
              <li key={p} className="flex items-center gap-2 rounded-md bg-muted/50 px-2 py-1 font-mono text-xs">
                <span className="min-w-0 flex-1 truncate" title={p}>{p}</span>
                <button onClick={() => onRemove(p)} className="text-muted-foreground hover:text-foreground" aria-label={t("Remove", "移除")}><X className="h-3.5 w-3.5" /></button>
              </li>
            ))}
          </ul>
        )}
        <div className="flex gap-2">
          <Button size="sm" variant="outline" disabled={!selected.length || !!busy} onClick={() => run("inspect")}>
            {busy === "inspect" ? <Loader2 className="animate-spin" /> : <Search />} {t("Inspect", "检查")}
          </Button>
          {selected.length > 0 && <Button size="sm" variant="ghost" onClick={onClear}>{t("Clear", "清空")}</Button>}
        </div>
        {error && <Alert variant="error">{error}</Alert>}

        {info && (
          <div className="space-y-2">
            <p className="text-[13px]">
              {t(`${info.files} files`, `${info.files} 个文件`)}
              {info.bytes != null && ` · ${bytes(info.bytes)}`}
              {info.ignored ? t(` · ${info.ignored} not recognised`, ` · ${info.ignored} 个无法识别`) : ""}
              {info.described != null && info.described < info.files ? t(` · first ${info.described} described`, ` · 已描述前 ${info.described} 个`) : ""}
            </p>
            {info.groups.length > 0 ? (
              <div className="overflow-x-auto rounded-md border">
                <table className="w-full text-xs">
                  <thead className="bg-muted/60 text-muted-foreground">
                    <tr>
                      <th className="px-2 py-1.5 text-left font-medium">{vendor === "massive" ? t("Dataset", "数据集") : t("Dataset · schema", "数据集 · schema")}</th>
                      <th className="px-2 py-1.5 text-right font-medium">{t("Files", "文件")}</th>
                      <th className="px-2 py-1.5 text-left font-medium">{t("Dates", "日期")}</th>
                      <th className="px-2 py-1.5 text-left font-medium" />
                    </tr>
                  </thead>
                  <tbody>
                    {info.groups.map((g, i) => (
                      <tr key={i} className="border-t">
                        <td className="px-2 py-1.5 font-mono">{g.index ?? `${g.dataset} · ${g.schema}`}</td>
                        <td className="px-2 py-1.5 text-right tabular-nums">{g.files}</td>
                        <td className="px-2 py-1.5 font-mono">{g.start ?? "?"} → {g.end ?? "?"}</td>
                        <td className="px-2 py-1.5">
                          {vendor === "massive"
                            ? g.resolution === "quotes" ? <Badge variant="secondary">{t("BBO", "BBO")}</Badge>
                              : g.csv ? <Badge variant="warn">{t(`${g.csv} csv.gz → parquet`, `${g.csv} 个 csv.gz → parquet`)}</Badge> : null
                            : g.convertible ? <Badge variant="success">{t("convertible", "可转换")}</Badge> : <Badge variant="outline">{t("reference only", "仅参考数据")}</Badge>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Alert variant="warning">{t("Nothing convertible was found in the selection.", "所选内容中没有可转换的数据。")}</Alert>
            )}
            {info.first_error && <Alert variant="warning">{info.first_error}</Alert>}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-4 border-t pt-3 text-[13px]">
          <label className="flex items-center gap-1.5">
            <input type="checkbox" checked={convert} onChange={(e) => setConvert(e.target.checked)} />
            {t("Convert to QFinZero storage after import", "导入后转换为 QFinZero 存储")}
          </label>
          <IntervalPicker value={iv} onChange={setIv} />
          {vendor === "databento" && (
            <label className="flex items-center gap-1.5">
              {t("Parallel jobs", "并行数")}
              <input type="number" min={1} max={32} value={jobs} onChange={(e) => setJobs(Number(e.target.value) || 1)}
                className="h-8 w-16 rounded-md border border-input bg-card px-2" />
            </label>
          )}
        </div>
        <Button className="w-full" disabled={!selected.length || !!busy} onClick={() => run("import")}>
          {busy === "import" ? <Loader2 className="animate-spin" /> : <FolderInput />}
          {convert ? t("Import and convert", "导入并转换") : t("Import", "导入")}
        </Button>
      </CardContent>
    </Card>
  );
}

// ── credentials and downloads ─────────────────────────────────────────────

function Credentials({ vendor, ready, onSaved }: { vendor: Vendor; ready: boolean; onSaved: () => void }) {
  const t = useT();
  const [form, setForm] = React.useState<Record<string, string>>({});
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState<{ ok: boolean; text: string } | null>(null);
  React.useEffect(() => { setForm({}); setMsg(null); }, [vendor]);
  const fields = vendor === "databento"
    ? [{ k: "api_key", label: t("API key", "API 密钥"), placeholder: "db-…", secret: true }]
    : [
        { k: "s3_access_key_id", label: t("S3 access key ID", "S3 Access Key ID"), placeholder: "", secret: false },
        { k: "s3_secret_access_key", label: t("S3 secret access key", "S3 Secret Access Key"), placeholder: "", secret: true },
        { k: "s3_endpoint", label: t("S3 endpoint", "S3 端点"), placeholder: "https://files.massive.com", secret: false },
      ];
  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const patch = Object.fromEntries(Object.entries(form).filter(([, v]) => v.trim()));
      await dataAdmin.putConfig(vendor === "databento" ? { databento: patch } : { massive: patch });
      setForm({});
      setMsg({ ok: true, text: t("Saved on the server.", "已保存到服务器。") });
      onSaved();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2"><KeyRound className="h-4 w-4" /> {t("Credentials", "凭证")}</CardTitle>
          <CardDescription>{t("Stored by the data service on the server; never shown again.", "由数据服务保存在服务器上，之后不再显示。")}</CardDescription>
        </div>
        {ready ? <Badge variant="success"><CheckCircle2 className="h-3 w-3" /> {t("configured", "已配置")}</Badge>
               : <Badge variant="warn">{t("not set", "未设置")}</Badge>}
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3 md:grid-cols-3">
          {fields.map((f) => (
            <label key={f.k} className="space-y-1">
              <span className="text-xs text-muted-foreground">{f.label}</span>
              <input className={cn(inputCls, "font-mono")} type={f.secret ? "password" : "text"} autoComplete="off"
                placeholder={ready && f.secret ? "••••••••" : f.placeholder} value={form[f.k] ?? ""}
                onChange={(e) => setForm({ ...form, [f.k]: e.target.value })} />
            </label>
          ))}
        </div>
        <div className="flex items-center gap-3">
          <Button size="sm" onClick={save} disabled={busy || !Object.values(form).some((v) => v.trim())}>
            {busy && <Loader2 className="animate-spin" />} {t("Save", "保存")}
          </Button>
          {msg && <span className={cn("text-[13px]", msg.ok ? "text-success" : "text-destructive")}>{msg.text}</span>}
        </div>
      </CardContent>
    </Card>
  );
}

function DownloadPanel({ vendor, indices, intervals, ready, onJob }: {
  vendor: Vendor; indices: string[]; intervals: QuoteIntervals; ready: boolean; onJob: (j: Job) => void;
}) {
  const [iv, setIv] = React.useState<QuoteIntervals>(intervals);
  React.useEffect(() => setIv(intervals), [intervals]);
  const t = useT();
  const [db, setDb] = React.useState({ dataset: "EQUS.MINI", schema: "ohlcv-1m", symbols: "SPY,QQQ", stype_in: "raw_symbol", start: "", end: "", max_cost: "0" });
  const [ms, setMs] = React.useState({ index: indices[0] ?? "us_stocks_sip/day_aggs_v1", start: "", end: "" });
  const [quote, setQuote] = React.useState<DownloadQuote | null>(null);
  const [busy, setBusy] = React.useState<"" | "quote" | "run">("");
  const [convert, setConvert] = React.useState(true);
  React.useEffect(() => setQuote(null), [vendor, db, ms]);

  const params = (): Record<string, unknown> =>
    vendor === "databento"
      ? { ...db, symbols: db.symbols.split(/[\s,]+/).filter(Boolean), max_cost: Number(db.max_cost) || 0, end: db.end || db.start }
      : { ...ms, end: ms.end || ms.start };
  const valid = vendor === "databento" ? Boolean(db.dataset && db.schema && db.symbols.trim() && db.start) : Boolean(ms.index && ms.start);

  const go = async (what: "quote" | "run") => {
    setBusy(what);
    try {
      if (what === "quote") setQuote(await dataAdmin.quote(vendor, params()));
      else onJob(await dataAdmin.download(vendor, params(), convert, iv));
    } catch (e) {
      setQuote({ ok: false, error: (e as Error).message });
    } finally {
      setBusy("");
    }
  };

  const field = (label: string, el: React.ReactNode) => (
    <label className="space-y-1"><span className="text-xs text-muted-foreground">{label}</span>{el}</label>
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><CloudDownload className="h-4 w-4" /> {t("Download request", "下载请求")}</CardTitle>
        <CardDescription>
          {vendor === "databento"
            ? t("Quote first (free). Paid data needs a cost ceiling; files already on disk are not fetched again.", "先报价（免费）。付费数据需要设置费用上限；磁盘上已有的文件不会重复下载。")
            : t("Plan first: the bucket listing shows how many days and bytes are missing. Days on disk are skipped.", "先预览：列出缺少的天数和数据量。磁盘上已有的日期会跳过。")}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {vendor === "databento" ? (
          <div className="grid gap-3 md:grid-cols-4">
            {field(t("Dataset", "数据集"), (
              <>
                <input list="db-datasets" className={cn(inputCls, "font-mono")} value={db.dataset} onChange={(e) => setDb({ ...db, dataset: e.target.value.trim() })} />
                <datalist id="db-datasets">{DATABENTO_DATASETS.map((d) => <option key={d} value={d} />)}</datalist>
              </>
            ))}
            {field("Schema", (
              <select className={inputCls} value={db.schema} onChange={(e) => setDb({ ...db, schema: e.target.value })}>
                {DATABENTO_SCHEMAS.map((s) => <option key={s}>{s}</option>)}
              </select>
            ))}
            {field(t("Symbols", "代码"), <input className={cn(inputCls, "font-mono")} value={db.symbols} placeholder="SPY,QQQ  ·  SPY.OPT" onChange={(e) => setDb({ ...db, symbols: e.target.value })} />)}
            {field(t("Symbol type", "代码类型"), (
              <select className={inputCls} value={db.stype_in} onChange={(e) => setDb({ ...db, stype_in: e.target.value })}>
                <option value="raw_symbol">raw_symbol</option>
                <option value="parent">{t("parent (e.g. SPY.OPT)", "parent（如 SPY.OPT）")}</option>
              </select>
            ))}
            {field(t("Start", "开始"), <input type="date" className={inputCls} value={db.start} onChange={(e) => setDb({ ...db, start: e.target.value })} />)}
            {field(t("End", "结束"), <input type="date" className={inputCls} value={db.end} min={db.start} onChange={(e) => setDb({ ...db, end: e.target.value })} />)}
            {field(t("Max cost (USD)", "费用上限（美元）"), <input type="number" min={0} step="0.5" className={inputCls} value={db.max_cost} onChange={(e) => setDb({ ...db, max_cost: e.target.value })} />)}
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-3">
            {field(t("Dataset", "数据集"), (
              <select className={cn(inputCls, "font-mono")} value={ms.index} onChange={(e) => setMs({ ...ms, index: e.target.value })}>
                {indices.map((i) => <option key={i}>{i}</option>)}
              </select>
            ))}
            {field(t("Start", "开始"), <input type="date" className={inputCls} value={ms.start} onChange={(e) => setMs({ ...ms, start: e.target.value })} />)}
            {field(t("End", "结束"), <input type="date" className={inputCls} value={ms.end} min={ms.start} onChange={(e) => setMs({ ...ms, end: e.target.value })} />)}
          </div>
        )}
        {!ready && <Alert variant="warning">{t("Save the credentials above first.", "请先保存上方的凭证。")}</Alert>}
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="outline" disabled={!ready || !valid || !!busy} onClick={() => go("quote")}>
            {busy === "quote" ? <Loader2 className="animate-spin" /> : <Search />} {vendor === "databento" ? t("Get quote", "报价") : t("Plan", "预览")}
          </Button>
          <Button size="sm" disabled={!ready || !valid || !quote?.ok || !!busy} onClick={() => go("run")}>
            {busy === "run" ? <Loader2 className="animate-spin" /> : <CloudDownload />}
            {convert ? t("Download and convert", "下载并转换") : t("Download", "下载")}
          </Button>
          <label className="ml-2 flex items-center gap-1.5 text-[13px]">
            <input type="checkbox" checked={convert} onChange={(e) => setConvert(e.target.checked)} /> {t("convert afterwards", "下载后转换")}
          </label>
        </div>
        <IntervalPicker value={iv} onChange={setIv} />
        {vendor === "massive" && ms.index.endsWith("quotes_v1") && (
          <Alert variant="warning">{t("Tick quote flat files are very large (OPRA: hundreds of GB a day). Check the plan before downloading.",
            "逐笔报价 flat files 非常大（OPRA 每天数百 GB），下载前请先查看预览。")}</Alert>
        )}
        {quote && (
          <Alert variant={quote.ok ? "info" : "error"} title={quote.ok ? t("Quote", "报价") : t("Request refused", "请求被拒绝")}>
            {quote.error && <div>{quote.error}</div>}
            {(quote.lines ?? []).slice(-6).map((l, i) => <div key={i} className="font-mono text-xs">{l}</div>)}
          </Alert>
        )}
      </CardContent>
    </Card>
  );
}

// ── jobs ──────────────────────────────────────────────────────────────────

function JobsPanel({ focus, onFocus }: { focus: string | null; onFocus: (id: string | null) => void }) {
  const t = useT();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["setup", "jobs"], queryFn: dataAdmin.jobs, refetchInterval: 4000 });
  const job = useQuery({
    queryKey: ["setup", "job", focus],
    queryFn: () => dataAdmin.job(focus!),
    enabled: Boolean(focus),
    refetchInterval: (q) => (q.state.data && ["queued", "running"].includes(q.state.data.status) ? 1500 : false),
  });
  const done = job.data && !["queued", "running"].includes(job.data.status);
  React.useEffect(() => {
    if (done) qc.invalidateQueries({ queryKey: ["coverage"] });
  }, [done, qc]);
  const logRef = React.useRef<HTMLPreElement>(null);
  React.useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [job.data?.lines?.length]);
  const statusBadge = (s: Job["status"]) =>
    s === "done" ? <Badge variant="success">{t("done", "完成")}</Badge> : s === "error" ? <Badge variant="danger">{t("failed", "失败")}</Badge>
      : <Badge variant="warn"><Loader2 className="h-3 w-3 animate-spin" /> {s === "queued" ? t("queued", "排队中") : t("running", "运行中")}</Badge>;
  const jobs = (list.data?.jobs ?? []).slice(0, 12);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("Jobs", "任务")}</CardTitle>
        <CardDescription>{t("Imports, downloads and conversions run in the background; follow their logs here.", "导入、下载和转换在后台运行，可在此查看日志。")}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 lg:grid-cols-[280px_1fr]">
        <ul className="max-h-80 space-y-1 overflow-auto">
          {jobs.length === 0 && <li className="text-[13px] text-muted-foreground">{t("No jobs yet.", "还没有任务。")}</li>}
          {jobs.map((j) => (
            <li key={j.id}>
              <button onClick={() => onFocus(j.id)} className={cn("flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] hover:bg-accent", focus === j.id && "bg-secondary")}>
                <span className="min-w-0 flex-1 truncate">{j.label}</span>
                {statusBadge(j.status)}
              </button>
            </li>
          ))}
        </ul>
        <div className="min-w-0">
          {!focus && <p className="text-[13px] text-muted-foreground">{t("Select a job to see its log.", "选择一个任务查看日志。")}</p>}
          {job.data && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-[13px]"><span className="font-medium">{job.data.label}</span>{statusBadge(job.data.status)}
                {job.data.error && <span className="text-destructive">{job.data.error}</span>}</div>
              <pre ref={logRef} className="max-h-80 overflow-auto rounded-md border bg-muted/40 p-3 font-mono text-[11.5px] leading-relaxed">
                {(job.data.lines ?? []).join("\n") || t("waiting for output…", "等待输出…")}
              </pre>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

// ── page ──────────────────────────────────────────────────────────────────

type Tab = "local" | "download" | "status";

export function DataSetup() {
  const t = useT();
  const status = useQuery({ queryKey: ["setup", "status"], queryFn: dataAdmin.setupStatus });
  const [vendor, setVendor] = React.useState<Vendor>("databento");
  const [tab, setTab] = React.useState<Tab>("local");
  const [selected, setSelected] = React.useState<string[]>([]);
  const [focus, setFocus] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (window.location.hash === "#status") setTab("status");
  }, []);
  React.useEffect(() => setSelected([]), [vendor]);
  const toggle = (p: string) => setSelected((s) => (s.includes(p) ? s.filter((x) => x !== p) : [...s, p]));
  const s = status.data;

  return (
    <div className="space-y-4">
      {status.isError && <Alert variant="error" title={t("The data service is unreachable", "无法连接数据服务")}>{(status.error as Error).message}</Alert>}
      {s && (
        <div className="grid gap-3 md:grid-cols-3">
          {([
            [t("Converts into", "转换目标"), s.storage_root, null],
            [t("Databento library", "Databento 原始库"), s.libraries.databento, s.credentials.databento],
            [t("massive library", "massive 原始库"), s.libraries.massive, s.credentials.massive],
          ] as const).map(([k, v, cred]) => (
            <div key={k} className="rounded-md border bg-card px-3 py-2">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                {k}
                {cred !== null && (cred ? <Badge variant="success">{t("key set", "已设密钥")}</Badge> : <Badge variant="outline">{t("no key", "无密钥")}</Badge>)}
              </div>
              <div className="mt-0.5 truncate font-mono text-[13px]" title={v}>{v}</div>
            </div>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Segmented value={vendor} onChange={setVendor} options={[{ value: "databento", label: "Databento" }, { value: "massive", label: "massive" }] as const} />
        <div className="flex items-center gap-1 border-b">
          {([["local", t("Local files", "本地文件"), FolderInput], ["download", t("Download", "下载"), CloudDownload], ["status", t("Storage status", "存储状态"), HardDrive]] as const).map(([id, label, Icon]) => (
            <button key={id} onClick={() => setTab(id)} role="tab" aria-selected={tab === id}
              className={cn("-mb-px inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium", tab === id ? "border-primary" : "border-transparent text-muted-foreground hover:text-foreground")}>
              <Icon className="h-4 w-4" /> {label}
            </button>
          ))}
        </div>
      </div>

      {tab === "local" && (
        <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
          <FileBrowser selected={selected} onToggle={toggle} />
          <ImportPanel vendor={vendor} selected={selected} intervals={s?.quote_intervals ?? { stock: 1, option: 1, future: 1 }}
            onRemove={toggle} onClear={() => setSelected([])}
            onJob={(j) => { setFocus(j.id); setSelected([]); }} />
        </div>
      )}
      {tab === "download" && s && (
        <div className="space-y-4">
          <Credentials vendor={vendor} ready={s.credentials[vendor]} onSaved={() => status.refetch()} />
          <DownloadPanel vendor={vendor} indices={s.massive_indices} intervals={s.quote_intervals}
            ready={s.credentials[vendor]} onJob={(j) => setFocus(j.id)} />
        </div>
      )}
      {tab === "status" && <StorageStatus />}
      {tab !== "status" && <JobsPanel focus={focus} onFocus={setFocus} />}
    </div>
  );
}
