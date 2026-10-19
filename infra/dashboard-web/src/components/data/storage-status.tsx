"use client";

// Storage status: per source, whether local raw files are converted and how far
// the data is behind today. "Update" first shows what it would do (days to
// fetch from massive with which key and how much, days to convert, or that
// nothing is new) and runs only after confirmation.

import { Fragment, useEffect, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { CheckCircle2, CloudDownload, Info, Loader2, Play, RefreshCw, Search, ShieldCheck, X } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useT } from "@/components/locale-provider";
import { fmtBytes, JobProgressView } from "@/components/data/data-utility";
import { dataAdmin, type Job, type RefreshItem, type Source } from "@/lib/data-admin";
import { cn } from "@/lib/utils";

const DOT: Record<Source["colour"], string> = {
  green: "bg-success",
  amber: "bg-warning",
  red: "bg-destructive",
  grey: "bg-muted-foreground/40",
};

function SubHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 className="text-[15px] font-semibold">{title}</h2>
        {description && <p className="text-[13px] text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

function useJob(id: string | null) {
  const [job, setJob] = useState<Job | null>(null);
  useEffect(() => {
    if (!id) return;
    let stop = false;
    const tick = async () => {
      try {
        const j = await dataAdmin.job(id);
        if (stop) return;
        setJob(j);
        if (j.status === "queued" || j.status === "running") setTimeout(tick, 1200);
      } catch {
        if (!stop) setTimeout(tick, 3000);
      }
    };
    tick();
    return () => {
      stop = true;
    };
  }, [id]);
  return job;
}

type Tab = "layout" | "keys" | "local" | "download" | "status";
type PlanState = { loading: boolean; items?: RefreshItem[]; error?: string };

/** One source's plan, in words, with the action to confirm. */
function PlanLine({ it, onGoTo }: { it: RefreshItem; onGoTo?: (t: Tab) => void }) {
  const t = useT();
  const f = it.fetch;
  if (it.action === "fetch" && f) {
    return (
      <span>
        {f.gaps
          ? t(`massive has ${f.files} trading day(s) missing locally (${f.first} – ${f.last}; ${f.gaps} fill a gap), about ${fmtBytes(f.bytes)}, using key ${f.key?.label ?? "?"}.`,
              `massive 上有 ${f.files} 个本地缺少的交易日（${f.first} – ${f.last}，其中 ${f.gaps} 天是中间的缺口），约 ${fmtBytes(f.bytes)}，使用密钥 ${f.key?.label ?? "?"}。`)
          : t(`massive has ${f.files} new trading day(s) (${f.first} – ${f.last}), about ${fmtBytes(f.bytes)}, using key ${f.key?.label ?? "?"}.`,
              `massive 上有 ${f.files} 个新交易日（${f.first} – ${f.last}），约 ${fmtBytes(f.bytes)}，使用密钥 ${f.key?.label ?? "?"}。`)}
      </span>
    );
  }
  if (it.action === "convert") {
    return <span>{t(`${it.convert_days} day(s) of local raw data are not converted yet.`, `有 ${it.convert_days} 天本地原始数据尚未转换。`)}
      {f?.error && <span className="text-destructive"> {"massive: "}{f.error}</span>}</span>;
  }
  if (it.action === "manual") {
    const text = it.id === "us_databento"
      ? t("Databento bills per request, so it is never downloaded automatically. Quote and accept it under Download.", "Databento 按请求计费，不会自动下载。请到“下载”页报价并确认。")
      : it.id === "cn_stock_daily"
        ? t("Tushare has no downloader here. Import a new dump under Local files.", "Tushare 没有内置下载器，请在“本地文件”中导入新的导出文件。")
        : t("No local data yet. Choose the first date range under Download.", "本地还没有数据，请先在“下载”页选择首次下载的日期范围。");
    return (
      <span>{text}{" "}
        {onGoTo && <button className="font-medium text-primary hover:underline" onClick={() => onGoTo(it.id === "cn_stock_daily" ? "local" : "download")}>
          {it.id === "cn_stock_daily" ? t("Local files", "本地文件") : t("Download", "下载")} →</button>}
      </span>
    );
  }
  if (f?.error) return <span className="text-destructive">{"massive: "}{f.error}</span>;
  const until = it.raw_max ?? it.store_max;
  if (!until) return <span>{t("Nothing to update.", "没有需要更新的内容。")}</span>;
  return f
    ? <span>{t(`Up to date: massive has nothing after ${until}.`, `已是最新：massive 上 ${until} 之后没有新数据。`)}</span>
    : <span>{t(`Up to date: everything up to ${until} is converted.`, `已是最新：截至 ${until} 的数据都已转换。`)}</span>;
}

function PlanBox({ state, single, onRun, onClose, onGoTo, busy }: {
  state: PlanState; single?: boolean; onRun: (fetch: boolean) => void; onClose: () => void; onGoTo?: (t: Tab) => void; busy: boolean;
}) {
  const t = useT();
  const items = state.items ?? [];
  const fetchN = items.filter((i) => i.action === "fetch");
  const convertN = items.filter((i) => i.action === "convert");
  const nothing = items.length > 0 && !fetchN.length && !convertN.length;
  const bytes = fetchN.reduce((a, i) => a + (i.fetch?.bytes ?? 0), 0);
  return (
    <div className={cn("flex items-start gap-3 rounded-lg border px-3 py-2.5 text-[13px]",
      state.error ? "border-destructive/30 bg-destructive/5" : nothing ? "border-success/30 bg-success/5" : "border-primary/25 bg-primary/[0.04]")}>
      {state.loading ? <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-muted-foreground" />
        : nothing ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
          : <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" />}
      <div className="min-w-0 flex-1 space-y-1">
        {state.loading && <span className="text-muted-foreground">{t("Asking the vendor what is new…", "正在向供应商查询新数据…")}</span>}
        {state.error && <span className="text-destructive">{state.error}</span>}
        {items.map((it) => (
          <div key={it.id}>{!single && <span className="mr-1.5 font-mono text-[12px] font-medium">{it.id}</span>}<PlanLine it={it} onGoTo={onGoTo} /></div>
        ))}
        {!state.loading && !state.error && (fetchN.length > 0 || convertN.length > 0) && (
          <div className="flex flex-wrap gap-2 pt-1.5">
            <button disabled={busy} onClick={() => onRun(fetchN.length > 0)}
                    className="inline-flex h-7 items-center gap-1.5 rounded-md bg-primary px-3 text-[12.5px] font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
              {fetchN.length ? <CloudDownload className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
              {fetchN.length ? t(`Download ${fmtBytes(bytes)} and convert`, `下载 ${fmtBytes(bytes)} 并转换`) : t("Convert", "转换")}
            </button>
            {fetchN.length > 0 && convertN.length > 0 && (
              <button disabled={busy} onClick={() => onRun(false)} className="h-7 rounded-md border px-3 text-[12.5px] hover:bg-accent disabled:opacity-50">{t("Convert local only", "仅转换本地")}</button>
            )}
          </div>
        )}
      </div>
      <button onClick={onClose} className="rounded p-0.5 text-muted-foreground hover:bg-accent" aria-label={t("Close", "关闭")}><X className="h-3.5 w-3.5" /></button>
    </div>
  );
}

export function StorageStatus({ onGoTo }: { onGoTo?: (t: Tab) => void }) {
  const t = useT();
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["data", "status"], queryFn: dataAdmin.sources, refetchInterval: 30_000 });
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobFor, setJobFor] = useState<string | null>(null);
  const [plans, setPlans] = useState<Record<string, PlanState>>({});
  const [error, setError] = useState("");
  const job = useJob(jobId);
  const running = job?.status === "queued" || job?.status === "running";

  useEffect(() => {
    if (job && !running) qc.invalidateQueries({ queryKey: ["data", "status"] });
  }, [job, running, qc]);

  const check = async (key: string) => {
    setPlans((p) => ({ ...p, [key]: { loading: true } }));
    try {
      const r = await dataAdmin.refreshPlan(key === "__all" ? "prices" : key);
      setPlans((p) => ({ ...p, [key]: { loading: false, items: r.items } }));
    } catch (e) {
      setPlans((p) => ({ ...p, [key]: { loading: false, error: (e as Error).message } }));
    }
  };
  const run = async (key: string, fetch: boolean) => {
    setError("");
    try {
      const j = await dataAdmin.startUpdate({ source: key === "__all" ? "prices" : key, fetch });
      setJobId(j.id);
      setJobFor(key);
      setPlans((p) => { const n = { ...p }; delete n[key]; return n; });
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const close = (key: string) => setPlans((p) => { const n = { ...p }; delete n[key]; return n; });

  const sources = status.data?.sources ?? [];
  const stateLabel = (s: Source) =>
    s.state === "fresh" ? t("converted", "已转换")
      : s.state === "behind" ? t(`${s.behind_days ?? "?"} d to convert`, `待转换 ${s.behind_days ?? "?"} 天`)
        : s.state === "missing" ? t("not converted", "未转换")
          : s.state === "no_raw" ? t("no raw data", "无原始数据")
            : s.state === "unavailable" ? t("unavailable", "不可用") : s.state;
  const lagLabel = (s: Source) =>
    s.lag_days == null ? "—" : s.lag_days <= 1 ? t("current", "最新") : t(`${s.lag_days} trading days behind`, `落后 ${s.lag_days} 个交易日`);
  const lastRun = (r: NonNullable<Source["last_run"]>) =>
    r.reason === "fetched" && r.status === "ok" ? t(`fetched ${r.fetched_days ?? ""} d`, `补齐 ${r.fetched_days ?? ""} 天`)
      : r.status === "ok" ? t(`converted ${(r.rows ?? 0).toLocaleString()} rows`, `转换 ${(r.rows ?? 0).toLocaleString()} 行`)
        : r.status === "skipped" ? t("nothing new", "无新数据")
          : r.status === "error" ? t("failed", "失败") : (r.status ?? "—");
  const jobStatus = (s: Job["status"]) =>
    ({ queued: t("queued", "排队中"), running: t("running", "运行中"), done: t("done", "完成"), error: t("error", "失败"),
      cancelled: t("cancelled", "已取消"), interrupted: t("interrupted", "已中断") })[s] ?? s;
  const summary = (j: Job) => {
    const lines = j.lines ?? [];
    if (lines.some((l) => l.includes("already up to date"))) return t("Already up to date; nothing new.", "已是最新，没有新数据。");
    const rows = lines.map((l) => /rows=\s*([\d,]+)/.exec(l)?.[1]).filter(Boolean).map((x) => Number(String(x).replace(/,/g, "")));
    const total = rows.reduce((a, b) => a + b, 0);
    return total ? t(`${total.toLocaleString()} rows converted.`, `已转换 ${total.toLocaleString()} 行。`) : "";
  };

  return (
    <div className="space-y-5">
      <SubHeader
        title={t("Storage status", "存储状态")}
        description={t(
          "Raw vendor data against converted UPQ storage. Update fetches the new days from massive (after you confirm) and converts them.",
          "供应商原始数据与已转换的 UPQ 存储对照。“更新”会先列出 massive 上的新交易日，确认后下载并转换。",
        )}
        actions={
          <>
            <Link href="/sanity" className={buttonVariants({ variant: "ghost", size: "sm" })}>
              <ShieldCheck /> {t("Data checks", "数据检查")}
            </Link>
            <button onClick={() => status.refetch()} className={buttonVariants({ variant: "outline", size: "sm" })}>
              <RefreshCw className={status.isFetching ? "animate-spin" : ""} /> {t("Refresh", "刷新")}
            </button>
            <button disabled={running || plans.__all?.loading} onClick={() => check("__all")} className={buttonVariants({ size: "sm" })}>
              <Search /> {t("Check for new data", "检查新数据")}
            </button>
          </>
        }
      />
      {error && <p className="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}
      {plans.__all && <PlanBox state={plans.__all} onRun={(f) => run("__all", f)} onClose={() => close("__all")} onGoTo={onGoTo} busy={running} />}
      {job && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-[15px]">
              {running ? <Loader2 className="h-4 w-4 animate-spin" /> : job.status === "done" ? <CheckCircle2 className="h-4 w-4 text-success" /> : null} {job.label}
            </CardTitle>
            <CardDescription>
              {jobStatus(job.status)}{!running && job.status === "done" && summary(job) ? ` · ${summary(job)}` : ""}{job.error ? ` · ${job.error}` : ""}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {job.progress && Object.keys(job.progress).length > 0 && <JobProgressView p={job.progress} running={running} />}
            <pre className="max-h-60 overflow-auto rounded-lg bg-muted p-3 font-mono text-xs leading-relaxed text-foreground">
              {(job.lines ?? []).join("\n") || t("waiting for output…", "等待输出…")}
            </pre>
          </CardContent>
        </Card>
      )}
      <Card>
        <CardHeader>
          <CardTitle>{t("Sources", "数据源")}</CardTitle>
          <CardDescription>{t("Converted: every local raw day is in the store. Behind: trading days between the newest converted day and today.",
            "已转换：本地原始数据都已进入存储。落后：最新转换日到今天之间的交易日数。")}</CardDescription>
        </CardHeader>
        <CardContent>
          {status.isLoading && <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />}
          {status.isError && <p className="text-sm text-destructive">{t("data-admin is unreachable: ", "无法连接 data-admin：")}{(status.error as Error).message}</p>}
          {sources.length > 0 && (
            <div className="overflow-x-auto rounded-lg border">
              <table className="w-full text-sm">
                <thead className="bg-secondary/50 text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2">{t("Source", "数据源")}</th><th className="px-3 py-2">{t("Conversion", "转换")}</th>
                    <th className="px-3 py-2">{t("Data until", "数据截至")}</th><th className="px-3 py-2">{t("Behind today", "落后")}</th>
                    <th className="px-3 py-2">{t("Last run", "上次运行")}</th><th className="px-3 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {sources.map((s) => {
                    const mine = jobFor === s.id && running;
                    const plan = plans[s.id];
                    return (
                      <Fragment key={s.id}>
                        <tr className="border-t">
                          <td className="px-3 py-2">
                            <p className="font-medium">{s.id}</p>
                            <p className="text-xs text-muted-foreground">{s.domain}{s.market ? ` · ${s.market}` : ""}</p>
                          </td>
                          <td className="px-3 py-2 text-[13px]">
                            <span className={cn(s.state === "behind" || s.state === "missing" ? "font-medium text-warning" : "text-foreground/80")}>{stateLabel(s)}</span>
                          </td>
                          <td className="px-3 py-2 font-mono text-xs">
                            {s.store_max ?? "—"}
                            {s.raw_max && s.raw_max !== s.store_max && <span className="block text-[11px] text-muted-foreground">{t("raw", "原始")} {s.raw_max}</span>}
                          </td>
                          <td className="px-3 py-2 text-[13px]">
                            <span className="inline-flex items-center gap-1.5"><span className={`h-2.5 w-2.5 rounded-full ${DOT[s.colour]}`} />{lagLabel(s)}</span>
                          </td>
                          <td className="px-3 py-2 text-xs text-muted-foreground">
                            {mine ? <span className="inline-flex items-center gap-1 text-primary"><Loader2 className="h-3 w-3 animate-spin" />{t("running", "运行中")}</span>
                              : s.last_run?.last_run_ts ? <>{lastRun(s.last_run)} · {new Date(s.last_run.last_run_ts).toLocaleString()}</> : "—"}
                          </td>
                          <td className="px-3 py-2 text-right">
                            <button disabled={running || plan?.loading} onClick={() => check(s.id)}
                                    className="inline-flex items-center gap-1 rounded-md bg-secondary px-2.5 py-1 text-xs font-medium hover:bg-secondary/80 disabled:opacity-50">
                              {plan?.loading && <Loader2 className="h-3 w-3 animate-spin" />}{t("Update", "更新")}
                            </button>
                          </td>
                        </tr>
                        {plan && (
                          <tr>
                            <td colSpan={6} className="px-3 pb-3">
                              <PlanBox state={plan} single onRun={(f) => run(s.id, f)} onClose={() => close(s.id)} onGoTo={onGoTo} busy={running} />
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
