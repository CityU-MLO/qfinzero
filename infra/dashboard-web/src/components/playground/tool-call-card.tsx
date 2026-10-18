"use client";

import { useState } from "react";
import { Ban, CheckCircle2, ChevronDown, ChevronRight, CircleDashed, Loader2, Wrench, XCircle } from "lucide-react";

import { JsonViewer } from "@/components/news/json-viewer";
import { useT } from "@/components/locale-provider";
import { Segmented } from "@/components/ui/segmented";
import { callMs, type ToolCall, type ToolStatus } from "@/lib/chat-api";
import { cn } from "@/lib/utils";

export function StatusIcon({ status, className }: { status: ToolStatus; className?: string }) {
  const c = cn("h-3.5 w-3.5 shrink-0", className);
  switch (status) {
    case "running":
      return <Loader2 className={cn(c, "animate-spin text-warning")} />;
    case "pending":
      return <CircleDashed className={cn(c, "text-muted-foreground")} />;
    case "done":
      return <CheckCircle2 className={cn(c, "text-success")} />;
    case "cancelled":
      return <Ban className={cn(c, "text-muted-foreground")} />;
    default:
      return <XCircle className={cn(c, "text-destructive")} />;
  }
}

export const fmtMs = (ms: number | null | undefined) =>
  ms == null ? "" : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`;

/** ``a=1, tickers=SPY,QQQ`` — a one-line view of the arguments. */
export function argSummary(input: Record<string, unknown> | undefined, max = 80): string {
  if (!input) return "";
  const parts = Object.entries(input).map(([k, v]) =>
    `${k}=${Array.isArray(v) ? v.join(",") : typeof v === "object" && v !== null ? "{…}" : String(v)}`);
  const s = parts.join("  ");
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

type Row = Record<string, unknown>;

/** Rows of a tabular result (an array of objects, or ``{rows|data|results: [...]}``). */
function tableRows(output: unknown): Row[] | null {
  const arr = Array.isArray(output) ? output
    : output && typeof output === "object"
      ? (["rows", "data", "results", "items", "events", "bars"].map((k) => (output as Row)[k]).find(Array.isArray) as unknown[] | undefined)
      : undefined;
  if (!arr || !arr.length || !arr.every((r) => r && typeof r === "object" && !Array.isArray(r))) return null;
  return arr as Row[];
}

function cell(v: unknown): string {
  if (v == null) return "";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(Math.abs(v) < 1 ? 4 : 2);
  if (typeof v === "object") return JSON.stringify(v);
  const s = String(v);
  return s.length > 60 ? `${s.slice(0, 59)}…` : s;
}

export function OutputView({ output }: { output: unknown }) {
  const t = useT();
  const rows = tableRows(output);
  const [view, setView] = useState<"table" | "json">(rows ? "table" : "json");
  if (!rows) return <JsonViewer data={output} title={t("Output", "输出")} />;
  const cols = Array.from(new Set(rows.slice(0, 50).flatMap((r) => Object.keys(r)))).slice(0, 10);
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-medium text-muted-foreground">
          {t("Output", "输出")} · {rows.length} {t("rows", "行")}
        </span>
        <Segmented value={view} onChange={setView}
          options={[{ value: "table", label: t("Table", "表格") }, { value: "json", label: "JSON" }]} />
      </div>
      {view === "json" ? <JsonViewer data={output} title="JSON" /> : (
        <div className="max-h-72 overflow-auto rounded-md border">
          <table className="w-full text-[11px]">
            <thead className="sticky top-0 bg-muted text-muted-foreground">
              <tr>{cols.map((c) => <th key={c} className="px-2 py-1 text-left font-medium">{c}</th>)}</tr>
            </thead>
            <tbody className="font-mono">
              {rows.slice(0, 200).map((r, i) => (
                <tr key={i} className="border-t">
                  {cols.map((c) => <td key={c} className="whitespace-nowrap px-2 py-0.5">{cell(r[c])}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length > 200 && (
            <div className="border-t px-2 py-1 text-[11px] text-muted-foreground">
              {t(`First 200 of ${rows.length} rows; JSON has all.`, `仅显示前 200 行（共 ${rows.length} 行），JSON 中有全部数据。`)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function ToolCallCard({ call, defaultOpen = false }: { call: ToolCall; defaultOpen?: boolean }) {
  const t = useT();
  const [open, setOpen] = useState(defaultOpen);
  const ms = callMs(call);
  return (
    <div className="overflow-hidden rounded-md border bg-card text-sm">
      <button className="flex w-full items-center gap-2 px-3 py-1.5 text-left transition-colors hover:bg-muted/60"
        onClick={() => setOpen(!open)}>
        <StatusIcon status={call.status} />
        <span className="font-mono text-xs font-medium text-foreground">{call.tool}</span>
        <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-muted-foreground">{argSummary(call.input)}</span>
        {ms != null && <span className="text-[11px] tabular-nums text-muted-foreground">{fmtMs(ms)}</span>}
        {open ? <ChevronDown className="h-3 w-3 text-muted-foreground" /> : <ChevronRight className="h-3 w-3 text-muted-foreground" />}
      </button>
      {open && (
        <div className="flex flex-col gap-2 px-3 pb-3">
          <JsonViewer data={call.input ?? {}} title={t("Input", "输入")} />
          {call.status === "done" && call.output !== undefined && <OutputView output={call.output} />}
          {call.status === "error" && <p className="font-mono text-xs text-destructive">{call.error ?? String(call.output ?? "")}</p>}
          {call.status === "cancelled" && <p className="text-xs text-muted-foreground">{t("Stopped before it finished.", "未完成即被停止。")}</p>}
        </div>
      )}
    </div>
  );
}

/** One model step's tool calls, collapsed to a line like "Used 3 tools". */
export function ToolGroup({ calls, onInspect }: { calls: ToolCall[]; onInspect?: () => void }) {
  const t = useT();
  const running = calls.some((c) => c.status === "running" || c.status === "pending");
  const failed = calls.filter((c) => c.status === "error").length;
  const [open, setOpen] = useState(false);
  const names = Array.from(new Set(calls.map((c) => c.tool)));
  const span = (() => {
    const s = calls.map((c) => c.started_at).filter(Boolean) as number[];
    const e = calls.map((c) => c.ended_at).filter(Boolean) as number[];
    return s.length && e.length ? Math.max(...e) - Math.min(...s) : null;
  })();
  return (
    <div className="w-full">
      <button onClick={() => setOpen(!open)}
        className="group flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-[13px] text-muted-foreground transition-colors hover:bg-muted/60">
        {running ? <Loader2 className="h-3.5 w-3.5 animate-spin text-warning" /> : <Wrench className="h-3.5 w-3.5" />}
        <span className="min-w-0 flex-1 truncate">
          {running ? t("Running ", "正在调用 ") : t("Used ", "调用了 ")}
          <span className="font-mono text-foreground">{names.slice(0, 3).join(", ")}</span>
          {names.length > 3 && ` +${names.length - 3}`}
          {calls.length > 1 && <span> · {calls.length} {t("calls", "次")}</span>}
          {failed > 0 && <span className="text-destructive"> · {failed} {t("failed", "失败")}</span>}
        </span>
        {span != null && !running && <span className="text-[11px] tabular-nums">{fmtMs(span)}</span>}
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
      </button>
      {open && (
        <div className="ml-3 mt-1 flex flex-col gap-1.5 border-l pl-3">
          {calls.map((c) => <ToolCallCard key={c.id} call={c} />)}
          {onInspect && (
            <button onClick={onInspect} className="w-fit text-[12px] text-primary hover:underline">
              {t("Open the run inspector", "打开运行视图")}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
