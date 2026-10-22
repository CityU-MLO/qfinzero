"use client";

import { useState } from "react";
import { Check, Copy, Loader2, Network, OctagonX, TriangleAlert } from "lucide-react";
import { Streamdown } from "streamdown";
import "streamdown/styles.css";

import { useT } from "@/components/locale-provider";
import { fmtTokens, type ChatMessage } from "@/lib/chat-api";

import { ToolGroup, fmtMs } from "./tool-call-card";

function CopyButton({ text }: { text: string }) {
  const t = useT();
  const [done, setDone] = useState(false);
  return (
    <button onClick={() => { void navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); }}
      className="rounded p-1 hover:bg-muted hover:text-foreground" title={t("Copy", "复制")} aria-label={t("Copy", "复制")}>
      {done ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}

export function MessageBubble({ message, onInspect }: { message: ChatMessage; onInspect?: () => void }) {
  const t = useT();
  if (message.role === "user") {
    return (
      <div className="group flex flex-col items-end gap-1">
        <div className="max-w-[85%] rounded-2xl bg-secondary px-4 py-2.5 text-sm leading-relaxed text-foreground">
          <p className="whitespace-pre-wrap">{message.content}</p>
        </div>
        <div className="opacity-0 transition group-hover:opacity-100 text-muted-foreground"><CopyButton text={message.content} /></div>
      </div>
    );
  }
  const running = message.status === "running";
  const calls = message.steps.reduce((n, s) => n + s.tool_calls.length, 0);
  const started = message.steps[0]?.started_at;
  const ended = message.steps.at(-1)?.ended_at;
  const empty = !message.steps.some((s) => s.text || s.tool_calls.length);
  return (
    <div className="group flex flex-col gap-2 text-sm leading-relaxed">
      {message.steps.map((s, i) => (
        <div key={i} className="flex flex-col gap-1.5">
          {s.text && <div className="min-w-0"><Streamdown>{s.text}</Streamdown></div>}
          {s.tool_calls.length > 0 && <ToolGroup calls={s.tool_calls} onInspect={onInspect} />}
          {running && s.retry && !s.ended_at && (
            <div className="flex items-center gap-1.5 text-[12px] text-warning" title={s.retry.error}>
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {t(`The model provider is busy; retrying in ${s.retry.delay_s} s (${s.retry.attempt}/${s.retry.of}).`,
                `模型服务繁忙，${s.retry.delay_s} 秒后重试（第 ${s.retry.attempt}/${s.retry.of} 次）。`)}
            </div>
          )}
        </div>
      ))}
      {running && empty && (
        <div className="flex items-center gap-1.5 text-muted-foreground">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary [animation-delay:150ms]" />
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary [animation-delay:300ms]" />
        </div>
      )}
      {message.status === "interrupted" && (
        <div className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
          <OctagonX className="h-3.5 w-3.5" /> {t("Stopped by you.", "已被你停止。")}
        </div>
      )}
      {message.status === "error" && (
        <div className="flex items-start gap-1.5 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-[12px] text-destructive">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" /> <span className="break-all">{message.error}</span>
        </div>
      )}
      {!running && (
        <div className="flex items-center gap-1 text-[11px] text-muted-foreground opacity-0 transition group-hover:opacity-100">
          {message.content && <CopyButton text={message.content} />}
          {calls > 0 && onInspect && (
            <button onClick={onInspect} className="flex items-center gap-1 rounded px-1.5 py-1 hover:bg-muted hover:text-foreground">
              <Network className="h-3.5 w-3.5" /> {t("Run", "运行过程")}
            </button>
          )}
          {message.model && <span className="px-1 font-mono">{message.model}</span>}
          {started && ended && <span className="px-1">{fmtMs(ended - started)}</span>}
          {message.usage?.input_tokens != null && (
            <span className="px-1">{fmtTokens(message.usage.input_tokens)} {t("in", "输入")} · {fmtTokens(message.usage.output_tokens)} {t("out", "输出")}</span>
          )}
        </div>
      )}
    </div>
  );
}
