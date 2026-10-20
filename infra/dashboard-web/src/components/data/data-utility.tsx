"use client";

import * as React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2, Database, FolderTree, HardDrive, KeyRound, Loader2, Pencil, Plus, ShieldCheck, Trash2, X,
} from "lucide-react";

import { useT } from "@/components/locale-provider";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { dataAdmin, type DirInfo, type JobProgress, type Vendor, type VendorKey } from "@/lib/data-admin";
import { cn } from "@/lib/utils";

const inputCls =
  "h-9 w-full rounded-md border border-input bg-card px-2.5 text-[13px] outline-none focus:border-ring focus:ring-2 focus:ring-ring/20";

export function fmtBytes(n?: number | null): string {
  if (n == null) return "—";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${u[i]}`;
}

export function fmtDuration(s?: number | null): string {
  if (s == null || !Number.isFinite(s)) return "—";
  if (s < 60) return `${Math.round(s)} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
  return `${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min`;
}

const money = (n?: number | null) => (n == null ? "—" : `$${n.toFixed(2)}`);

// ── progress ──────────────────────────────────────────────────────────────

export function ProgressBar({ value, tone = "primary" }: { value: number | null; tone?: "primary" | "warn" | "danger" | "muted" }) {
  const color = { primary: "bg-primary", warn: "bg-warning", danger: "bg-destructive", muted: "bg-muted-foreground/40" }[tone];
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
      {value == null ? <div className={cn("h-full w-1/3 animate-pulse rounded-full", color)} />
        : <div className={cn("h-full rounded-full transition-[width]", color)} style={{ width: `${Math.max(1, Math.min(100, value * 100))}%` }} />}
    </div>
  );
}

const STAGE: Record<string, [string, string]> = {
  quoted: ["quoted", "已报价"], planned: ["planned", "已规划"], downloading: ["downloading", "下载中"],
  converting: ["converting", "转换中"], done: ["finished", "完成"],
};

export function JobProgressView({ p, running }: { p?: JobProgress; running: boolean }) {
  const t = useT();
  if (!p || (!p.files_total && !p.bytes_total && !p.stage)) return null;
  const frac = p.bytes_total ? (p.bytes_done ?? 0) / p.bytes_total : p.files_total ? (p.files_done ?? 0) / p.files_total : null;
  const stage = p.stage ? (STAGE[p.stage] ? t(...STAGE[p.stage]) : p.stage) : "";
  return (
    <div className="space-y-1.5 rounded-md border px-3 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2 text-[12px]">
        <span className="font-medium">{stage}{p.current ? <span className="font-normal text-muted-foreground"> · {p.current}</span> : null}</span>
        <span className="tabular-nums text-muted-foreground">
          {p.files_total != null && <>{p.files_done ?? 0}/{p.files_total} {t("files", "个文件")}</>}
          {(p.files_failed ?? 0) > 0 && <span className="text-destructive"> · {p.files_failed} {t("failed", "失败")}</span>}
        </span>
      </div>
      <ProgressBar value={running && p.stage === "converting" ? null : frac} tone={(p.files_failed ?? 0) > 0 ? "warn" : "primary"} />
      <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-[11.5px] tabular-nums text-muted-foreground">
        {p.bytes_done != null && <span>{fmtBytes(p.bytes_done)}{p.bytes_total ? ` / ${fmtBytes(p.bytes_total)}` : ""}</span>}
        {p.rate_bps != null && running && <span>{fmtBytes(p.rate_bps)}/s</span>}
        {p.eta_s != null && running && <span>{t("left", "剩余")} {fmtDuration(p.eta_s)}</span>}
        {p.elapsed_s != null && <span>{t("elapsed", "已用")} {fmtDuration(p.elapsed_s)}</span>}
        {p.billable_bytes != null && <span>{t("billable", "计费")} {fmtBytes(p.billable_bytes)}</span>}
        {p.cost_usd != null && <span className={p.cost_usd > 0 ? "text-warning" : ""}>{t("cost", "费用")} {money(p.cost_usd)}</span>}
      </div>
    </div>
  );
}

// ── layouts ───────────────────────────────────────────────────────────────

function DirCard({ title, info, icon: Icon, edit, onEdit }: {
  title: string; info: DirInfo; icon: React.ComponentType<{ className?: string }>; edit: string | undefined; onEdit: (v: string) => void;
}) {
  const t = useT();
  const used = info.total_bytes && info.free_bytes != null ? 1 - info.free_bytes / info.total_bytes : null;
  return (
    <div className="space-y-2 rounded-lg border p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-sm font-medium"><Icon className="h-4 w-4 text-muted-foreground" /> {title}</span>
        {info.marker ? <Badge variant="success"><CheckCircle2 className="h-3 w-3" /> {t("initialised", "已初始化")}</Badge>
          : info.exists ? <Badge variant="warn">{t("no marker", "未初始化")}</Badge> : <Badge variant="outline">{t("missing", "不存在")}</Badge>}
      </div>
      <input className={cn(inputCls, "font-mono")} value={edit ?? info.path ?? ""} onChange={(e) => onEdit(e.target.value)} />
      <div className="text-[11.5px] text-muted-foreground">{info.holds}</div>
      {used != null && (
        <div className="space-y-1">
          <ProgressBar value={used} tone={used > 0.9 ? "danger" : used > 0.8 ? "warn" : "muted"} />
          <div className="text-[11px] tabular-nums text-muted-foreground">
            {fmtBytes(info.free_bytes)} {t("free of", "可用，共")} {fmtBytes(info.total_bytes)}{!info.writable && ` · ${t("read-only", "只读")}`}
          </div>
        </div>
      )}
    </div>
  );
}

function Compaction() {
  const t = useT();
  const [days, setDays] = React.useState(30);
  const [plan, setPlan] = React.useState<{ files?: number; bytes?: number; cutoff?: string } | null>(null);
  const [jobId, setJobId] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const job = useQuery({
    queryKey: ["setup", "job", jobId], queryFn: () => dataAdmin.job(jobId!), enabled: Boolean(jobId),
    refetchInterval: (q) => (q.state.data && ["queued", "running"].includes(q.state.data.status) ? 1500 : false),
  });
  const estimate = async () => {
    setBusy(true);
    try { setPlan(await dataAdmin.compact(days, true)); } finally { setBusy(false); }
  };
  const run = async () => {
    setBusy(true);
    try { setJobId((await dataAdmin.compact(days, false)).id); } finally { setBusy(false); }
  };
  const running = job.data && ["queued", "running"].includes(job.data.status);
  return (
    <div className="space-y-2 border-t pt-2">
      <div className="font-medium">{t("Archive compression", "归档压缩")}</div>
      <p className="text-[11.5px] text-muted-foreground">
        {t("Measured on real partitions: rewriting history at zstd 9 saves 3-6% and reads at the same speed; larger row groups would slow single-ticker queries 2-4x, so they are not used. New data stays at zstd 3.",
          "在真实分区上测得：把历史分区重写为 zstd 9 可节省 3–6%，读取速度不变；更大的行组会让单代码查询慢 2–4 倍，因此不采用。新数据仍使用 zstd 3。")}
      </p>
      <div className="flex flex-wrap items-center gap-2 text-[12.5px]">
        {t("Older than", "早于")}
        <input type="number" min={0} className="h-8 w-20 rounded-md border border-input bg-card px-2" value={days}
          onChange={(e) => { setDays(Number(e.target.value) || 0); setPlan(null); }} />
        {t("days", "天")}
        <Button size="sm" variant="outline" onClick={estimate} disabled={busy}>{t("Estimate", "估算")}</Button>
        <Button size="sm" onClick={run} disabled={busy || !plan?.files || Boolean(running)}>{t("Compress", "压缩")}</Button>
      </div>
      {plan && <div className="text-[12px] text-muted-foreground">
        {t(`${plan.files} files, ${fmtBytes(plan.bytes)} before ${plan.cutoff}.`, `${plan.cutoff} 之前共 ${plan.files} 个文件，${fmtBytes(plan.bytes)}。`)}
      </div>}
      {job.data && <JobProgressView p={job.data.progress} running={Boolean(running)} />}
      {job.data?.status === "done" && (job.data.lines ?? []).slice(-1).map((l) => (
        <div key={l} className="font-mono text-[11.5px] text-success">{l}</div>
      ))}
    </div>
  );
}

export function LayoutPanel() {
  const t = useT();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["setup", "layout"], queryFn: dataAdmin.layout });
  const [edits, setEdits] = React.useState<Record<string, string>>({});
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState<{ ok: boolean; text: string } | null>(null);
  const L = q.data;
  const changed = L ? Object.fromEntries(Object.entries(edits).filter(([k, v]) => {
    const cur = k === "storage_root" ? L.qfz.path : Object.values(L.raw).find((r) => r.config_key === k)?.path;
    return v.trim() && v.trim() !== cur;
  })) : {};
  const init = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await dataAdmin.initLayout(Object.keys(changed).length ? changed : undefined);
      setEdits({});
      const made = r.created.length ? t(`Created ${r.created.length} directories.`, `已创建 ${r.created.length} 个目录。`)
        : t("Everything was already in place.", "目录结构已就绪。");
      const left = r.skipped.length ? " " + t(`Left alone (existing data, edit the path to choose it): ${r.skipped.map((x) => x.path).join(", ")}`,
        `未改动（已有数据，修改路径即可明确选用）：${r.skipped.map((x) => x.path).join("、")}`) : "";
      setMsg({ ok: true, text: made + left });
      qc.invalidateQueries({ queryKey: ["setup"] });
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><FolderTree className="h-4 w-4" /> {t("Directories and layouts", "目录与数据布局")}</CardTitle>
        <CardDescription>
          {t("RAW libraries keep each vendor's own download layout and are only read; the QFZ store is the converted, query-ready layout UPQ serves. The paths are saved in the data configuration; Initialise creates the directories and marks what each one is.",
            "RAW 原始库保留各供应商自己的下载格式，只读不写；QFZ 存储是转换后、可直接查询的格式，由 UPQ 提供服务。路径保存在数据配置中；“初始化”会创建目录并标记每个目录的用途。")}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {q.isLoading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
        {q.isError && <Alert variant="error">{(q.error as Error).message}</Alert>}
        {L && (
          <>
            <div>
              <div className="mb-2 text-xs font-semibold text-muted-foreground">{t("RAW download layout", "RAW 下载格式")}</div>
              <div className="grid gap-3 lg:grid-cols-3">
                {(["massive", "databento", "tushare"] as const).map((v) => (
                  <DirCard key={v} title={v === "massive" ? "massive" : v === "databento" ? "Databento" : "Tushare"} info={L.raw[v]}
                    icon={HardDrive} edit={edits[L.raw[v].config_key]} onEdit={(x) => setEdits({ ...edits, [L.raw[v].config_key]: x })} />
                ))}
              </div>
            </div>
            <div>
              <div className="mb-2 text-xs font-semibold text-muted-foreground">{t("QFZ fast-access layout", "QFZ 快速读取格式")}</div>
              <div className="grid gap-3 lg:grid-cols-[1fr_1fr]">
                <DirCard title={t("QFZ store", "QFZ 存储")} info={L.qfz} icon={Database} edit={edits.storage_root}
                  onEdit={(x) => setEdits({ ...edits, storage_root: x })} />
                <div className="space-y-2 rounded-lg border p-3 text-[12.5px]">
                  <div className="font-medium">{t("Format", "格式")}</div>
                  <div className="font-mono text-[12px] text-muted-foreground">
                    parquet · {L.qfz.format.compression} level {L.qfz.format.level} · {L.qfz.format.row_group_rows.toLocaleString()} {t("rows per row group", "行/行组")}
                  </div>
                  {L.qfz.stores && (
                    <div className="flex flex-wrap gap-1 pt-1">
                      {Object.entries(L.qfz.stores).map(([s, ok]) => (
                        <span key={s} className={cn("rounded border px-1.5 py-0.5 font-mono text-[11px]", ok ? "text-foreground" : "text-muted-foreground line-through")}>{s}</span>
                      ))}
                    </div>
                  )}
                  <div className="pt-1 text-[11px] text-muted-foreground">{t("Config file", "配置文件")}: <span className="font-mono">{L.config_file}</span></div>
                  <Compaction />
                </div>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Button size="sm" onClick={init} disabled={busy}>
                {busy && <Loader2 className="animate-spin" />}
                {Object.keys(changed).length ? t("Save paths and initialise", "保存路径并初始化") : t("Initialise", "初始化")}
              </Button>
              {Object.keys(changed).length > 0 && (
                <Button size="sm" variant="outline" onClick={() => setEdits({})}>{t("Discard changes", "放弃修改")}</Button>
              )}
              {msg && <span className={cn("text-[13px]", msg.ok ? "text-success" : "text-destructive")}>{msg.text}</span>}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ── vendor keys ───────────────────────────────────────────────────────────

const SECRETS: Record<Vendor, { k: keyof VendorKey; en: string; zh: string }[]> = {
  databento: [{ k: "api_key", en: "API key", zh: "API 密钥" }],
  massive: [
    { k: "s3_access_key_id", en: "S3 access key ID", zh: "S3 Access Key ID" },
    { k: "s3_secret_access_key", en: "S3 secret", zh: "S3 Secret" },
    { k: "rest_api_key", en: "REST key (optional)", zh: "REST 密钥（可选）" },
  ],
};

function KeyEditor({ vendor, initial, catalog, onDone }: {
  vendor: Vendor; initial: VendorKey | null; catalog: { product: string; name: string }[]; onDone: () => void;
}) {
  const t = useT();
  const [label, setLabel] = React.useState(initial?.label ?? "");
  const [all, setAll] = React.useState(!initial || initial.products.includes("*"));
  const [products, setProducts] = React.useState<string[]>(initial?.products.filter((p) => p !== "*") ?? []);
  const [extra, setExtra] = React.useState("");
  const [budget, setBudget] = React.useState(initial?.monthly_budget_usd != null ? String(initial.monthly_budget_usd) : "");
  const [secrets, setSecrets] = React.useState<Record<string, string>>({});
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState("");
  const toggle = (p: string) => setProducts((x) => (x.includes(p) ? x.filter((y) => y !== p) : [...x, p]));
  const save = async () => {
    setBusy(true);
    setErr("");
    try {
      const custom = extra.split(/[\s,]+/).filter(Boolean);
      await dataAdmin.saveKey(vendor, {
        ...(initial ? { id: initial.id } : {}), label: label.trim() || undefined,
        products: all ? ["*"] : [...products, ...custom],
        ...(vendor === "databento" ? { monthly_budget_usd: budget.trim() ? Number(budget) : null } : {}),
        ...secrets,
      });
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-3 rounded-lg border bg-muted/20 p-3">
      <div className="grid gap-3 md:grid-cols-3">
        <label className="space-y-1">
          <span className="text-xs text-muted-foreground">{t("Name", "名称")}</span>
          <input className={inputCls} value={label} placeholder={t("e.g. CME futures", "例如 CME 期货")} onChange={(e) => setLabel(e.target.value)} />
        </label>
        {SECRETS[vendor].map((f) => (
          <label key={f.k} className="space-y-1">
            <span className="text-xs text-muted-foreground">{t(f.en, f.zh)}</span>
            <input className={cn(inputCls, "font-mono")} type="password" autoComplete="off"
              placeholder={initial?.[f.k] ? String(initial[f.k]) : ""} value={secrets[f.k] ?? ""}
              onChange={(e) => setSecrets({ ...secrets, [f.k]: e.target.value })} />
          </label>
        ))}
        {vendor === "databento" && (
          <label className="space-y-1">
            <span className="text-xs text-muted-foreground">{t("Monthly budget (USD, optional)", "每月预算（美元，可选）")}</span>
            <input className={inputCls} type="number" min={0} step="1" value={budget} onChange={(e) => setBudget(e.target.value)} />
          </label>
        )}
      </div>
      <div className="space-y-2">
        <label className="flex items-center gap-2 text-[13px]">
          <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />
          {t("This key covers every product", "这个密钥可用于所有产品")}
        </label>
        {!all && (
          <>
            <div className="flex flex-wrap gap-1.5">
              {catalog.map((c) => (
                <button key={c.product} type="button" onClick={() => toggle(c.product)} title={c.name}
                  className={cn("rounded-md border px-2 py-1 font-mono text-[11.5px]", products.includes(c.product) ? "border-primary bg-primary/10 text-foreground" : "text-muted-foreground hover:text-foreground")}>
                  {c.product}
                </button>
              ))}
            </div>
            <input className={cn(inputCls, "font-mono")} value={extra} onChange={(e) => setExtra(e.target.value)}
              placeholder={vendor === "databento" ? t("other datasets or patterns, e.g. XEUR.*", "其他数据集或通配符，例如 XEUR.*")
                : t("other indices or patterns, e.g. us_indices/*", "其他索引或通配符，例如 us_indices/*")} />
          </>
        )}
      </div>
      {err && <Alert variant="error">{err}</Alert>}
      <div className="flex gap-2">
        <Button size="sm" onClick={save} disabled={busy}>{busy && <Loader2 className="animate-spin" />} {t("Save key", "保存密钥")}</Button>
        <Button size="sm" variant="outline" onClick={onDone}>{t("Cancel", "取消")}</Button>
      </div>
    </div>
  );
}

export function KeysPanel() {
  const t = useT();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["setup", "keys"], queryFn: dataAdmin.keys });
  const [editing, setEditing] = React.useState<{ vendor: Vendor; key: VendorKey | null } | null>(null);
  const [tests, setTests] = React.useState<Record<string, { busy?: boolean; ok?: boolean; text?: string; access?: Record<string, boolean> }>>({});
  const [confirm, setConfirm] = React.useState<string | null>(null);
  const done = () => { setEditing(null); qc.invalidateQueries({ queryKey: ["setup"] }); };
  const test = async (vendor: Vendor, k: VendorKey) => {
    setTests((x) => ({ ...x, [k.id]: { busy: true } }));
    try {
      const r = await dataAdmin.testKey(vendor, k.id);
      const ok = r.ok;
      const text = !ok ? r.error ?? "" : vendor === "databento" ? t(`Key accepted (${r.datasets} datasets listed).`, `密钥有效（列出 ${r.datasets} 个数据集）。`)
        : t(`Can list ${Object.values(r.access ?? {}).filter(Boolean).length} of ${Object.keys(r.access ?? {}).length} products.`,
          `可访问 ${Object.keys(r.access ?? {}).length} 个产品中的 ${Object.values(r.access ?? {}).filter(Boolean).length} 个。`);
      setTests((x) => ({ ...x, [k.id]: { ok, text, access: r.access } }));
    } catch (e) {
      setTests((x) => ({ ...x, [k.id]: { ok: false, text: (e as Error).message } }));
    }
  };
  const scopeTo = async (k: VendorKey, access: Record<string, boolean>) => {
    await dataAdmin.saveKey("massive", { id: k.id, products: Object.keys(access).filter((p) => access[p]) });
    done();
  };
  const data = q.data;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><KeyRound className="h-4 w-4" /> {t("Vendor keys", "供应商密钥")}</CardTitle>
        <CardDescription>
          {t("Databento and massive sell products separately, so keep one key per subscription or a single key for everything. A download uses the first key whose products cover it. Keys are stored on the server and shown masked.",
            "Databento 和 massive 的产品分别订阅：可以每个订阅一个密钥，也可以用一个全权限密钥。下载时使用第一个涵盖该产品的密钥。密钥保存在服务器上，只显示末四位。")}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {q.isLoading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
        {q.isError && <Alert variant="error">{(q.error as Error).message}</Alert>}
        {data && (["databento", "massive"] as const).map((vendor) => (
          <section key={vendor} className="space-y-2">
            <div className="flex items-center justify-between">
              <div className="text-sm font-semibold">{vendor === "databento" ? "Databento" : "massive"}</div>
              <Button size="sm" variant="outline" onClick={() => setEditing({ vendor, key: null })}><Plus /> {t("Add key", "添加密钥")}</Button>
            </div>
            {data.keys[vendor].length === 0 && !editing && (
              <p className="text-[13px] text-muted-foreground">{t("No key yet.", "还没有密钥。")}</p>
            )}
            <div className="space-y-2">
              {data.keys[vendor].map((k) => {
                const spent = data.spend.by_key[k.id];
                const tr = tests[k.id];
                if (editing?.key?.id === k.id && editing.vendor === vendor) {
                  return <KeyEditor key={k.id} vendor={vendor} initial={k} catalog={data.catalog[vendor]} onDone={done} />;
                }
                return (
                  <div key={k.id} className="rounded-lg border px-3 py-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[13px] font-medium">{k.label || k.id}</span>
                      <span className="font-mono text-[11.5px] text-muted-foreground">{SECRETS[vendor].map((f) => k[f.k]).filter(Boolean).join(" · ")}</span>
                      <span className="flex flex-wrap gap-1">
                        {k.products.map((p) => (
                          <span key={p} className="rounded bg-secondary px-1.5 py-0.5 font-mono text-[11px]">{p === "*" ? t("all products", "所有产品") : p}</span>
                        ))}
                      </span>
                      <span className="ml-auto flex items-center gap-1">
                        <Button size="sm" variant="ghost" onClick={() => test(vendor, k)} disabled={tr?.busy}>
                          {tr?.busy ? <Loader2 className="animate-spin" /> : <ShieldCheck />} {t("Test", "测试")}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setEditing({ vendor, key: k })}><Pencil /> {t("Edit", "编辑")}</Button>
                        {confirm === k.id ? (
                          <>
                            <Button size="sm" variant="ghost" className="text-destructive"
                              onClick={async () => { await dataAdmin.deleteKey(vendor, k.id); setConfirm(null); done(); }}>{t("Delete", "删除")}</Button>
                            <Button size="sm" variant="ghost" onClick={() => setConfirm(null)}><X /></Button>
                          </>
                        ) : <Button size="sm" variant="ghost" onClick={() => setConfirm(k.id)} aria-label={t("Delete", "删除")}><Trash2 /></Button>}
                      </span>
                    </div>
                    {vendor === "databento" && (spent != null || k.monthly_budget_usd != null) && (
                      <div className="mt-1.5 space-y-1">
                        <div className="text-[11.5px] tabular-nums text-muted-foreground">
                          {t("This month", "本月")} {money(spent ?? 0)}{k.monthly_budget_usd != null && ` / ${money(k.monthly_budget_usd)} ${t("budget", "预算")}`}
                        </div>
                        {k.monthly_budget_usd ? <ProgressBar value={(spent ?? 0) / k.monthly_budget_usd} tone={(spent ?? 0) / k.monthly_budget_usd > 0.9 ? "danger" : "warn"} /> : null}
                      </div>
                    )}
                    {tr?.text && (
                      <div className={cn("mt-1.5 text-[12px]", tr.ok ? "text-success" : "text-destructive")}>
                        {tr.text}
                        {tr.access && tr.ok && (
                          <>
                            <div className="mt-1 flex flex-wrap gap-1">
                              {Object.entries(tr.access).map(([p, ok]) => (
                                <span key={p} className={cn("rounded border px-1.5 py-0.5 font-mono text-[11px]", ok ? "border-success/40 text-foreground" : "text-muted-foreground line-through")}>{p}</span>
                              ))}
                            </div>
                            <button className="mt-1 text-primary hover:underline" onClick={() => scopeTo(k, tr.access!)}>
                              {t("Scope the key to these products", "将密钥范围设为这些产品")}
                            </button>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
              {editing && editing.vendor === vendor && editing.key === null && (
                <KeyEditor vendor={vendor} initial={null} catalog={data.catalog[vendor]} onDone={done} />
              )}
            </div>
          </section>
        ))}
        {data && data.spend.recent.length > 0 && (
          <section className="space-y-1">
            <div className="text-xs font-semibold text-muted-foreground">
              {t(`Databento spend in ${data.spend.month}`, `${data.spend.month} Databento 花费`)}: {money(data.spend.total)}
            </div>
            <table className="w-full text-[12px]">
              <tbody>
                {data.spend.recent.slice(0, 8).map((r, i) => (
                  <tr key={i} className="border-t">
                    <td className="py-1 tabular-nums text-muted-foreground">{r.ts.slice(0, 16).replace("T", " ")}</td>
                    <td className="py-1 font-mono">{r.dataset} {r.schema}</td>
                    <td className="py-1 text-muted-foreground">{r.key_id}</td>
                    <td className="py-1 text-right tabular-nums">{r.files} {t("files", "个文件")}</td>
                    <td className="py-1 text-right tabular-nums text-warning">{money(r.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}
      </CardContent>
    </Card>
  );
}
