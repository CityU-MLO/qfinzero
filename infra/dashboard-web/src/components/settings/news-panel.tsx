"use client";

// Settings → News: the MongoDB the news lives in, how much each collection
// holds, and one collection per vendor. The shared collection (ticker_news) is
// read by other services too, so it is never changed: vendors are copied out
// of it ("Split by vendor"), and QFZ switches to reading the vendor
// collections once the copies are complete.

import * as React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Database, FileUp, Loader2, Newspaper, PlugZap, Split } from "lucide-react";

import { fmtBytes } from "@/components/data/data-utility";
import { useT } from "@/components/locale-provider";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { dataAdmin, type Job, type NewsCollUsage } from "@/lib/data-admin";
import { cn } from "@/lib/utils";

const inputCls =
  "w-full rounded-md border border-input bg-card px-3 py-1.5 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/20";

function useJob(id: string | null, onEnd: () => void) {
  const [job, setJob] = React.useState<Job | null>(null);
  const end = React.useRef(onEnd);
  end.current = onEnd;
  React.useEffect(() => {
    if (!id) return;
    let stop = false;
    const tick = async () => {
      try {
        const j = await dataAdmin.job(id);
        if (stop) return;
        setJob(j);
        if (j.status === "queued" || j.status === "running") setTimeout(tick, 2000);
        else end.current();
      } catch {
        if (!stop) setTimeout(tick, 4000);
      }
    };
    void tick();
    return () => { stop = true; };
  }, [id]);
  return job;
}

function JobLine({ job }: { job: Job | null }) {
  const t = useT();
  if (!job) return null;
  const p = job.progress ?? {};
  const pct = p.files_total ? Math.min(100, Math.round(((p.files_done ?? 0) / p.files_total) * 100)) : null;
  const running = job.status === "queued" || job.status === "running";
  return (
    <div className="space-y-1.5 rounded-lg border px-3 py-2 text-[13px]">
      <div className="flex items-center gap-2">
        {running && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
        <span className="font-medium">{job.label}</span>
        <Badge variant={job.status === "done" ? "success" : job.status === "error" ? "danger" : "secondary"}>{job.status}</Badge>
        {p.stage && running && <span className="text-muted-foreground">{p.stage}{p.current ? ` · ${p.current}` : ""}</span>}
        {pct != null && <span className="ml-auto font-mono text-xs">{(p.files_done ?? 0).toLocaleString()} / {p.files_total!.toLocaleString()}</span>}
      </div>
      {pct != null && running && (
        <div className="h-1.5 overflow-hidden rounded bg-muted"><div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} /></div>
      )}
      {job.error && <div className="text-xs text-destructive">{job.error}</div>}
      {!running && job.lines && job.lines.length > 0 && (
        <pre className="max-h-32 overflow-auto whitespace-pre-wrap font-mono text-[11px] text-muted-foreground">{job.lines.slice(-8).join("\n")}</pre>
      )}
      {!running && !job.lines?.length && <div className="text-xs text-muted-foreground">{t("finished", "已结束")}</div>}
    </div>
  );
}

function day(iso?: string | null) {
  return iso ? iso.slice(0, 10) : "—";
}

export function NewsPanel() {
  const t = useT();
  const qc = useQueryClient();
  const usage = useQuery({ queryKey: ["news", "usage"], queryFn: dataAdmin.newsUsage, refetchInterval: 30_000 });
  const s = usage.data?.settings;
  const [uri, setUri] = React.useState("");
  const [db, setDb] = React.useState("");
  const [msg, setMsg] = React.useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [splitId, setSplitId] = React.useState<string | null>(null);
  const [importId, setImportId] = React.useState<string | null>(null);
  const [importPath, setImportPath] = React.useState("");

  React.useEffect(() => {
    if (s) {
      setUri((u) => u || s.mongo_uri);
      setDb((d) => d || s.mongo_db);
    }
  }, [s]);

  const refresh = React.useCallback(() => void qc.invalidateQueries({ queryKey: ["news", "usage"] }), [qc]);
  const splitJob = useJob(splitId, refresh);
  const importJob = useJob(importId, refresh);

  const run = async (f: () => Promise<void>) => {
    setBusy(true);
    setMsg(null);
    try {
      await f();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const test = () => run(async () => {
    const r = await dataAdmin.newsTest(uri, db);
    setMsg(r.ok
      ? { ok: true, text: t(`Connected: MongoDB ${r.version}, ${r.database} has ${r.collections?.length ?? 0} collection(s): ${(r.collections ?? []).join(", ")}`,
          `已连接：MongoDB ${r.version}，${r.database} 有 ${r.collections?.length ?? 0} 个集合：${(r.collections ?? []).join("、")}`) }
      : { ok: false, text: r.error ?? "failed" });
  });
  const save = () => run(async () => {
    await dataAdmin.newsSave({ mongo_uri: uri, mongo_db: db });
    setMsg({ ok: true, text: t("Saved. ESP picks up the change within 15 seconds.", "已保存，ESP 会在 15 秒内切换。") });
    refresh();
  });
  const setMode = (mode: "legacy" | "vendor") => run(async () => {
    await dataAdmin.newsSave({ mode });
    setMsg({ ok: true, text: mode === "vendor"
      ? t("QFZ now reads the vendor collections; new imports go to them too.", "QFZ 现在读取各数据商的集合，新导入也写入这些集合。")
      : t("QFZ reads the shared collection again.", "QFZ 改回读取共享集合。") });
    refresh();
  });
  const split = () => run(async () => setSplitId((await dataAdmin.newsSplit()).id));
  const doImport = () => run(async () => {
    const paths = importPath.split(/\n|,/).map((x) => x.trim()).filter(Boolean);
    setImportId((await dataAdmin.newsImport(paths)).id);
  });

  const u = usage.data;
  const shared = u?.shared;
  const sources = u?.sources ?? [];
  const enabled = sources.filter((x) => x.enabled);
  // a vendor's copy is complete when it holds at least what the shared collection has under its prefix;
  // the usage view does not count per prefix (too slow on the shared collection), so we ask for "exists and non-empty"
  const ready = enabled.length > 0 && enabled.every((x) => x.exists && (x.documents ?? 0) > 0);
  const splitting = splitJob && (splitJob.status === "queued" || splitJob.status === "running");
  const reading = new Set(u?.read_from ?? []);

  const row = (label: React.ReactNode, c: NewsCollUsage | undefined, extra?: React.ReactNode) => (
    <tr className="border-t" key={c?.collection}>
      <td className="px-3 py-2">{label}</td>
      <td className="px-3 py-2 font-mono text-xs">{c?.collection}
        {c && reading.has(c.collection) && <Badge variant="success" className="ml-1.5">{t("read", "读取中")}</Badge>}</td>
      {c?.exists ? (
        <>
          <td className="px-3 py-2 text-right font-mono text-xs">{(c.documents ?? 0).toLocaleString()}</td>
          <td className="px-3 py-2 text-right font-mono text-xs">{fmtBytes(c.storage_bytes)}</td>
          <td className="px-3 py-2 text-right font-mono text-xs">{fmtBytes(c.index_bytes)}</td>
          <td className="px-3 py-2 font-mono text-xs">{day(c.first)} → {day(c.last)}</td>
        </>
      ) : (
        <td className="px-3 py-2 text-xs text-muted-foreground" colSpan={4}>{t("not created yet", "尚未创建")}</td>
      )}
      <td className="px-3 py-2 text-xs text-muted-foreground">{extra}</td>
    </tr>
  );

  return (
    <Card id="news" className="scroll-mt-20">
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Newspaper className="h-4 w-4" />{t("News storage", "新闻存储")}</CardTitle>
        <CardDescription>
          {t("News is kept in MongoDB, one collection per vendor. The shared collection is read by other services and is never modified: vendors are copied out of it, and QFZ switches to the vendor collections once the copies are complete.",
            "新闻存放在 MongoDB，每个数据商一个集合。共享集合也被其他服务读取，不会被修改：各数据商的数据从中复制出来，复制完成后 QFZ 再切换到数据商集合。")}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-2 md:grid-cols-[1fr_200px_auto]">
          <input className={cn(inputCls, "font-mono text-[13px]")} value={uri} onChange={(e) => setUri(e.target.value)}
                 placeholder="mongodb://host:27017" aria-label="MongoDB URI" />
          <input className={cn(inputCls, "font-mono text-[13px]")} value={db} onChange={(e) => setDb(e.target.value)}
                 placeholder="market_news" aria-label={t("Database", "数据库")} />
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={test} disabled={busy}><PlugZap /> {t("Test", "测试")}</Button>
            <Button size="sm" onClick={save} disabled={busy}>{t("Save", "保存")}</Button>
          </div>
        </div>

        {usage.isLoading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
        {u && !u.ok && <Alert variant="error">{t("Cannot reach MongoDB: ", "无法连接 MongoDB：")}{u.error}</Alert>}
        {u?.ok && u.database && (
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[13px]">
            <span className="flex items-center gap-1.5"><Database className="h-3.5 w-3.5" />MongoDB {u.version} · <b>{u.database.name}</b></span>
            <span>{t("data", "数据")} {fmtBytes(u.database.data_bytes)}</span>
            <span>{t("on disk", "磁盘")} {fmtBytes(u.database.storage_bytes)}</span>
            <span>{t("indexes", "索引")} {fmtBytes(u.database.index_bytes)}</span>
            {u.database.fs_total_bytes ? (
              <span className="text-muted-foreground">{t("volume", "磁盘卷")} {fmtBytes(u.database.fs_used_bytes)} / {fmtBytes(u.database.fs_total_bytes)}</span>
            ) : null}
          </div>
        )}

        {u?.ok && (
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-[13px]">
              <thead className="bg-secondary/50 text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2">{t("Vendor", "数据商")}</th>
                  <th className="px-3 py-2">{t("Collection", "集合")}</th>
                  <th className="px-3 py-2 text-right">{t("Documents", "文档数")}</th>
                  <th className="px-3 py-2 text-right">{t("On disk", "磁盘")}</th>
                  <th className="px-3 py-2 text-right">{t("Indexes", "索引")}</th>
                  <th className="px-3 py-2">{t("Published (UTC)", "发布时间（UTC）")}</th>
                  <th className="px-3 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {row(<span>{t("Shared (all vendors)", "共享（全部数据商）")}</span>, shared, t("kept unchanged", "保持不变"))}
                {sources.map((x) => row(
                  <span>{x.vendor} <span className="text-xs text-muted-foreground">· {x.market.toUpperCase()}</span></span>,
                  x, <span className="font-mono">{x.prefix}*</span>))}
              </tbody>
            </table>
          </div>
        )}

        {u?.ok && s && (
          <div className="space-y-3 rounded-lg border px-4 py-3">
            <div className="flex flex-wrap items-center gap-3 text-[13px]">
              <span className="font-medium">{t("QFZ reads from", "QFZ 读取")}</span>
              <div className="flex rounded-md border bg-background p-0.5">
                {(["legacy", "vendor"] as const).map((m) => (
                  <button key={m} onClick={() => m !== s.mode && setMode(m)} disabled={busy || (m === "vendor" && !ready)}
                          className={cn("rounded px-2 py-0.5 text-xs font-medium disabled:opacity-40",
                            s.mode === m ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")}>
                    {m === "legacy" ? t("shared collection", "共享集合") : t("vendor collections", "数据商集合")}
                  </button>
                ))}
              </div>
              <Button size="sm" variant="outline" onClick={split} disabled={busy || !!splitting}>
                <Split /> {enabled.some((x) => x.exists) ? t("Refresh vendor copies", "刷新数据商副本") : t("Split by vendor", "按数据商拆分")}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              {s.mode === "vendor"
                ? t("New imports are written to the vendor collections. The shared collection is no longer updated by QFZ.",
                    "新导入写入数据商集合，QFZ 不再更新共享集合。")
                : t("Copying runs on the MongoDB server and can take a while for tens of millions of documents; re-running only refreshes. Switch once each vendor collection is filled.",
                    "复制在 MongoDB 服务器端执行，数千万条文档需要一段时间；重复执行只会刷新。各数据商集合填满后再切换。")}
            </p>
            <JobLine job={splitJob} />
          </div>
        )}

        <div className="space-y-2">
          <div className="text-[13px] font-medium">{t("Import Benzinga news from the server", "从服务器导入 Benzinga 新闻")}</div>
          <div className="flex gap-2">
            <input className={cn(inputCls, "font-mono text-[13px]")} value={importPath} onChange={(e) => setImportPath(e.target.value)}
                   placeholder="/data/news/Benzinga_News_2026-09.zip" />
            <Button size="sm" variant="outline" onClick={doImport} disabled={busy || !importPath.trim()}><FileUp /> {t("Import", "导入")}</Button>
          </div>
          <p className="text-xs text-muted-foreground">
            {t("A YYYY-MM.jsonl[.gz] file, a folder of them, or a Benzinga .zip archive (checked against its manifest). Written to ",
              "可以是 YYYY-MM.jsonl[.gz] 文件、包含这些文件的文件夹，或 Benzinga .zip 压缩包（会对照清单校验）。写入 ")}
            <span className="font-mono">{s ? (s.mode === "vendor" ? s.sources.find((x) => x.id === "benzinga")?.collection : s.legacy_collection) : ""}</span>.
          </p>
          <JobLine job={importJob} />
        </div>

        {msg && <Alert variant={msg.ok ? "success" : "error"}>{msg.text}</Alert>}
      </CardContent>
    </Card>
  );
}
