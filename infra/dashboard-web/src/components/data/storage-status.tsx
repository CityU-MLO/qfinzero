"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { Loader2, Play, RefreshCw, ShieldCheck, TestTube2 } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useT } from "@/components/locale-provider";
import { dataAdmin, type Job, type Source } from "@/lib/data-admin";

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
        if (j.status === "queued" || j.status === "running") setTimeout(tick, 1500);
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

export function StorageStatus() {
  const t = useT();
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["data", "status"], queryFn: dataAdmin.sources, refetchInterval: 30_000 });
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const job = useJob(jobId);
  const running = job?.status === "queued" || job?.status === "running";

  useEffect(() => {
    if (job && !running) qc.invalidateQueries({ queryKey: ["data", "status"] });
  }, [job, running, qc]);

  const start = async (source: string, dry_run: boolean) => {
    setError("");
    try {
      setJobId((await dataAdmin.startUpdate({ source, dry_run })).id);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const sources = status.data?.sources ?? [];
  const jobStatus = (s: Job["status"]) =>
    s === "queued" ? t("queued", "排队中") : s === "running" ? t("running", "运行中") : s === "done" ? t("done", "完成") : t("error", "失败");
  return (
    <div className="space-y-5">
      <SubHeader
        title={t("Storage status", "存储状态")}
        description={t(
          "Raw vendor data against converted UPQ storage. Updates convert new raw files only.",
          "供应商原始数据与已转换的 UPQ 存储对照。更新只转换新的原始文件。",
        )}
        actions={
          <>
          <Link href="/sanity" className={buttonVariants({ variant: "ghost", size: "sm" })}>
            <ShieldCheck /> {t("Data checks", "数据检查")}
          </Link>
          <button onClick={() => status.refetch()} className={buttonVariants({ variant: "outline", size: "sm" })}>
            <RefreshCw className={status.isFetching ? "animate-spin" : ""} /> {t("Refresh", "刷新")}
          </button>
          <button disabled={running} onClick={() => start("prices", true)} className={buttonVariants({ variant: "outline", size: "sm" })}>
            <TestTube2 /> {t("Plan all", "全部预演")}
          </button>
          <button disabled={running} onClick={() => start("prices", false)} className={buttonVariants({ size: "sm" })}>
            <Play /> {t("Update all prices", "更新全部价格")}
          </button>
          </>
        }
      />
      {error && <p className="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}
      <Card>
        <CardHeader>
          <CardTitle>{t("Sources", "数据源")}</CardTitle>
          <CardDescription>{t("Lag counts business days since the newest converted date.", "延迟为自最新转换日期以来的交易日数。")}</CardDescription>
        </CardHeader>
        <CardContent>
          {status.isLoading && <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />}
          {status.isError && <p className="text-sm text-destructive">{t("data-admin is unreachable: ", "无法连接 data-admin：")}{(status.error as Error).message}</p>}
          {sources.length > 0 && (
            <div className="overflow-x-auto rounded-lg border">
              <table className="w-full text-sm">
                <thead className="bg-secondary/50 text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2">{t("Source", "数据源")}</th><th className="px-3 py-2">{t("State", "状态")}</th><th className="px-3 py-2">{t("Raw until", "原始数据截至")}</th>
                    <th className="px-3 py-2">{t("Converted until", "已转换截至")}</th><th className="px-3 py-2">{t("Last run", "上次运行")}</th><th className="px-3 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {sources.map((s) => (
                    <tr key={s.id} className="border-t">
                      <td className="px-3 py-2">
                        <p className="font-medium">{s.id}</p>
                        <p className="text-xs text-muted-foreground">{s.domain}{s.market ? ` · ${s.market}` : ""}</p>
                      </td>
                      <td className="px-3 py-2">
                        <span className="inline-flex items-center gap-1.5"><span className={`h-2.5 w-2.5 rounded-full ${DOT[s.colour]}`} />{s.state}</span>
                      </td>
                      <td className="px-3 py-2 font-mono text-xs">{s.raw_max ?? "—"}</td>
                      <td className="px-3 py-2 font-mono text-xs">{s.store_max ?? "—"}</td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">{s.last_run?.status ?? "—"}</td>
                      <td className="space-x-1 px-3 py-2 text-right">
                        <button disabled={running} onClick={() => start(s.id, true)} className="rounded-md px-2 py-1 text-xs hover:bg-accent disabled:opacity-50">{t("Plan", "预演")}</button>
                        <button disabled={running} onClick={() => start(s.id, false)} className="rounded-md bg-secondary px-2 py-1 text-xs font-medium hover:bg-secondary/80 disabled:opacity-50">{t("Update", "更新")}</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
      {job && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              {running && <Loader2 className="h-4 w-4 animate-spin" />} {job.label}
            </CardTitle>
            <CardDescription>{t("Job", "任务")} {job.id} · {jobStatus(job.status)}{job.error ? ` · ${job.error}` : ""}</CardDescription>
          </CardHeader>
          <CardContent>
            <pre className="max-h-80 overflow-auto rounded-lg bg-muted p-4 font-mono text-xs leading-relaxed text-foreground">
              {(job.lines ?? []).join("\n") || t("waiting for output…", "等待输出…")}
            </pre>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
