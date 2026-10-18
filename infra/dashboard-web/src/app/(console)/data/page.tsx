"use client";

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Database, Loader2, Play, RefreshCw, TestTube2 } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { dataAdmin, type Job, type Source } from "@/lib/data-admin";

const DOT: Record<Source["colour"], string> = {
  green: "bg-emerald-500",
  amber: "bg-amber-400",
  red: "bg-red-500",
  grey: "bg-slate-300",
};

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

export default function DataPage() {
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
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-2xl font-bold tracking-tight"><Database className="h-5 w-5 text-primary" /> Data</h2>
          <p className="mt-1 text-sm text-muted-foreground">Raw vendor data vs. converted UPQ storage. Updates convert new raw files only.</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => status.refetch()} className="flex h-9 items-center gap-1.5 rounded-lg border bg-white px-3 text-sm hover:bg-accent">
            <RefreshCw className={`h-4 w-4 ${status.isFetching ? "animate-spin" : ""}`} /> Refresh
          </button>
          <button disabled={running} onClick={() => start("prices", true)} className="flex h-9 items-center gap-1.5 rounded-lg border bg-white px-3 text-sm hover:bg-accent disabled:opacity-50">
            <TestTube2 className="h-4 w-4" /> Plan all
          </button>
          <button disabled={running} onClick={() => start("prices", false)} className="flex h-9 items-center gap-1.5 rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
            <Play className="h-4 w-4" /> Update all prices
          </button>
        </div>
      </div>
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      <Card>
        <CardHeader>
          <CardTitle>Sources</CardTitle>
          <CardDescription>Lag counts business days since the newest converted date.</CardDescription>
        </CardHeader>
        <CardContent>
          {status.isLoading && <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />}
          {status.isError && <p className="text-sm text-red-700">data-admin is unreachable: {(status.error as Error).message}</p>}
          {sources.length > 0 && (
            <div className="overflow-x-auto rounded-xl border">
              <table className="w-full text-sm">
                <thead className="bg-secondary/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2">Source</th><th className="px-3 py-2">State</th><th className="px-3 py-2">Raw until</th>
                    <th className="px-3 py-2">Converted until</th><th className="px-3 py-2">Last run</th><th className="px-3 py-2" />
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
                        <button disabled={running} onClick={() => start(s.id, true)} className="rounded-md px-2 py-1 text-xs hover:bg-accent disabled:opacity-50">Plan</button>
                        <button disabled={running} onClick={() => start(s.id, false)} className="rounded-md bg-secondary px-2 py-1 text-xs font-medium hover:bg-secondary/80 disabled:opacity-50">Update</button>
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
            <CardDescription>Job {job.id} · {job.status}{job.error ? ` · ${job.error}` : ""}</CardDescription>
          </CardHeader>
          <CardContent>
            <pre className="max-h-80 overflow-auto rounded-xl bg-slate-950 p-4 font-mono text-xs leading-relaxed text-slate-100">
              {(job.lines ?? []).join("\n") || "waiting for output…"}
            </pre>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
