"use client";

import { useEffect, useMemo, useState } from "react";
import { Bot, ChevronRight, ListTree, MessageSquare, Network, X } from "lucide-react";

import { useT } from "@/components/locale-provider";
import { JsonViewer } from "@/components/news/json-viewer";
import { Segmented } from "@/components/ui/segmented";
import { callMs, type ChatMessage, type ToolCall } from "@/lib/chat-api";
import { cn } from "@/lib/utils";

import { OutputView, StatusIcon, ToolCallCard, argSummary, fmtMs } from "./tool-call-card";

type Node =
  | { kind: "user"; key: string }
  | { kind: "model"; key: string; step: number }
  | { kind: "tool"; key: string; step: number; call: ToolCall }
  | { kind: "answer"; key: string };

const STATUS_RING: Record<string, string> = {
  done: "border-success/50", running: "border-warning", pending: "border-border",
  error: "border-destructive", cancelled: "border-border border-dashed",
};

/** The flow of one assistant turn: model steps and the tool calls each made,
 * as a graph (parallel calls stacked) and a timeline on a shared time axis. */
function Flow({ message, userText }: { message: ChatMessage; userText: string }) {
  const t = useT();
  const [sel, setSel] = useState<string>("");
  const steps = message.steps;

  const columns: Node[][] = useMemo(() => {
    const cols: Node[][] = [[{ kind: "user", key: "user" }]];
    steps.forEach((s, i) => {
      cols.push([{ kind: "model", key: `m${i}`, step: i }]);
      if (s.tool_calls.length) cols.push(s.tool_calls.map((c) => ({ kind: "tool" as const, key: c.id, step: i, call: c })));
    });
    if (message.content) cols.push([{ kind: "answer", key: "answer" }]);
    return cols;
  }, [steps, message.content]);

  const all = columns.flat();
  const selected = all.find((n) => n.key === sel) ?? null;

  // timeline
  const spans = [
    ...steps.map((s, i) => ({ key: `m${i}`, label: t(`Model · step ${i + 1}`, `模型 · 第 ${i + 1} 步`), a: s.started_at, b: s.ended_at ?? undefined, status: "done", model: true })),
    ...steps.flatMap((s) => s.tool_calls.map((c) => ({ key: c.id, label: c.tool, a: c.started_at, b: c.ended_at, status: c.status, model: false }))),
  ].filter((x) => x.a);
  const t0 = Math.min(...spans.map((x) => x.a as number));
  const t1 = Math.max(...spans.map((x) => (x.b ?? x.a) as number), t0 + 1);
  const ordered = spans.sort((x, y) => (x.a as number) - (y.a as number));

  return (
    <div className="flex flex-col gap-4">
      {/* graph */}
      <div className="overflow-x-auto rounded-md border bg-muted/30 p-3">
        <div className="flex w-max items-center gap-1">
          {columns.map((col, ci) => (
            <div key={ci} className="flex items-center gap-1">
              {ci > 0 && <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />}
              <div className="flex flex-col gap-1.5">
                {col.map((n) => {
                  const active = n.key === sel;
                  const base = "flex min-w-[120px] max-w-[220px] items-center gap-1.5 rounded-md border bg-card px-2 py-1.5 text-left text-[12px] transition hover:shadow-sm";
                  if (n.kind === "user")
                    return <button key={n.key} onClick={() => setSel(n.key)} className={cn(base, active && "ring-2 ring-ring/40")}>
                      <MessageSquare className="h-3.5 w-3.5 text-primary" /><span className="truncate">{t("You", "你")}</span></button>;
                  if (n.kind === "answer")
                    return <button key={n.key} onClick={() => setSel(n.key)} className={cn(base, active && "ring-2 ring-ring/40",
                      message.status === "interrupted" && "border-dashed")}>
                      <Bot className="h-3.5 w-3.5 text-primary" /><span className="truncate">
                        {message.status === "interrupted" ? t("Answer (stopped)", "回答（已停止）") : t("Answer", "回答")}</span></button>;
                  if (n.kind === "model") {
                    const s = steps[n.step];
                    const ms = s.started_at && s.ended_at ? s.ended_at - s.started_at : null;
                    return <button key={n.key} onClick={() => setSel(n.key)} className={cn(base, "bg-secondary", active && "ring-2 ring-ring/40")}>
                      <Bot className="h-3.5 w-3.5" /><span className="flex-1 truncate">{t(`Model ${n.step + 1}`, `模型 ${n.step + 1}`)}</span>
                      <span className="text-[10px] text-muted-foreground">{fmtMs(ms)}</span></button>;
                  }
                  return <button key={n.key} onClick={() => setSel(n.key)}
                    className={cn(base, "border-2", STATUS_RING[n.call.status] ?? "", active && "ring-2 ring-ring/40")}>
                    <StatusIcon status={n.call.status} /><span className="flex-1 truncate font-mono">{n.call.tool}</span>
                    <span className="text-[10px] text-muted-foreground">{fmtMs(callMs(n.call))}</span></button>;
                })}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* timeline */}
      {ordered.length > 0 && (
        <div className="rounded-md border p-3">
          <div className="mb-2 flex justify-between text-[11px] text-muted-foreground">
            <span>{t("Timeline", "时间线")}</span><span className="tabular-nums">{fmtMs(t1 - t0)}</span>
          </div>
          <div className="flex flex-col gap-1">
            {ordered.map((x) => {
              const left = (((x.a as number) - t0) / (t1 - t0)) * 100;
              const width = Math.max(0.8, ((((x.b ?? t1) as number) - (x.a as number)) / (t1 - t0)) * 100);
              return (
                <button key={x.key} onClick={() => setSel(x.key)} className="grid grid-cols-[150px_1fr_56px] items-center gap-2 text-left">
                  <span className={cn("truncate text-[11px]", x.model ? "text-foreground" : "font-mono text-muted-foreground")}>{x.label}</span>
                  <span className="relative h-3.5 rounded bg-muted">
                    <span className={cn("absolute top-0 h-full rounded",
                      x.model ? "bg-primary/60" : x.status === "error" ? "bg-destructive/70" : x.status === "cancelled" ? "bg-muted-foreground/40" : "bg-success/60",
                      x.key === sel && "ring-2 ring-ring")}
                      style={{ left: `${left}%`, width: `${Math.min(width, 100 - left)}%` }} />
                  </span>
                  <span className="text-right text-[11px] tabular-nums text-muted-foreground">
                    {fmtMs(x.b ? (x.b as number) - (x.a as number) : null)}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* detail of the selected node */}
      {selected && (
        <div className="rounded-md border p-3">
          {selected.kind === "user" && <p className="whitespace-pre-wrap text-sm">{userText}</p>}
          {selected.kind === "answer" && <p className="whitespace-pre-wrap text-sm">{message.content}</p>}
          {selected.kind === "model" && (
            <div className="space-y-2 text-sm">
              <div className="text-[11px] text-muted-foreground">
                {t("Tokens", "Token")}: {steps[selected.step].usage?.input_tokens ?? "—"} in · {steps[selected.step].usage?.output_tokens ?? "—"} out
                {" · "}{steps[selected.step].tool_calls.length} {t("tool calls", "次工具调用")}
              </div>
              {steps[selected.step].text ? <p className="whitespace-pre-wrap">{steps[selected.step].text}</p>
                : <p className="text-muted-foreground">{t("(no text, only tool calls)", "（没有文字，只调用了工具）")}</p>}
            </div>
          )}
          {selected.kind === "tool" && (
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-2 text-sm">
                <StatusIcon status={selected.call.status} /><span className="font-mono">{selected.call.tool}</span>
                <span className="text-[11px] text-muted-foreground">{fmtMs(callMs(selected.call))}</span>
              </div>
              <JsonViewer data={selected.call.input ?? {}} title={t("Input", "输入")} />
              {selected.call.status === "done" && <OutputView output={selected.call.output} />}
              {selected.call.status === "error" && <p className="font-mono text-xs text-destructive">{selected.call.error}</p>}
            </div>
          )}
        </div>
      )}
      {!selected && <p className="text-[12px] text-muted-foreground">{t("Click a node or a bar for its details.", "点击节点或时间条查看详情。")}</p>}
    </div>
  );
}

export function RunInspector({ message, userText, onClose }: { message: ChatMessage; userText: string; onClose: () => void }) {
  const t = useT();
  const [tab, setTab] = useState<"flow" | "record">("flow");
  const calls = message.steps.flatMap((s) => s.tool_calls);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const total = message.steps.length && message.steps[0].started_at
    ? (message.steps.at(-1)?.ended_at ?? Date.now()) - (message.steps[0].started_at as number) : null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={onClose}>
      <div className="flex h-full w-full max-w-3xl flex-col bg-card shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b px-4 py-3">
          <div>
            <div className="text-sm font-semibold">{t("Run", "运行过程")}</div>
            <div className="text-[11px] text-muted-foreground">
              {message.steps.length} {t("model steps", "个模型步骤")} · {calls.length} {t("tool calls", "次工具调用")}
              {total != null && ` · ${fmtMs(total)}`}
              {message.usage?.input_tokens != null && ` · ${message.usage.input_tokens} ${t("input tokens", "输入 token")}`}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Segmented value={tab} onChange={setTab} options={[
              { value: "flow", label: t("Flow", "流程"), icon: Network },
              { value: "record", label: t("Record", "记录"), icon: ListTree },
            ]} />
            <button onClick={onClose} className="rounded p-1 text-muted-foreground hover:bg-muted" aria-label={t("Close", "关闭")}>
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {tab === "flow" ? <Flow message={message} userText={userText} /> : (
            <div className="flex flex-col gap-3">
              {message.steps.map((s, i) => (
                <div key={i} className="flex flex-col gap-1.5">
                  <div className="text-[11px] font-medium text-muted-foreground">
                    {t(`Step ${i + 1}`, `第 ${i + 1} 步`)}{s.tool_calls.length ? ` · ${argSummary({ tools: s.tool_calls.map((c) => c.tool) })}` : ""}
                  </div>
                  {s.text && <p className="whitespace-pre-wrap rounded-md bg-muted/40 px-3 py-2 text-[13px]">{s.text}</p>}
                  {s.tool_calls.map((c) => <ToolCallCard key={c.id} call={c} />)}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
