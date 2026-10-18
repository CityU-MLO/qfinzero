"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Loader2, CheckCircle2, XCircle } from "lucide-react";
import { JsonViewer } from "@/components/news/json-viewer";
import { useT } from "@/components/locale-provider";

export type ToolCallStatus = "loading" | "done" | "error";

export interface ToolCallData {
  id: string;
  tool: string;
  input?: Record<string, unknown>;
  output?: unknown;
  error?: string;
  status: ToolCallStatus;
}

interface ToolCallCardProps {
  call: ToolCallData;
}

export function ToolCallCard({ call }: ToolCallCardProps) {
  const t = useT();
  const [expanded, setExpanded] = useState(false);

  const statusIcon = {
    loading: <Loader2 className="h-3.5 w-3.5 animate-spin text-warning" />,
    done: <CheckCircle2 className="h-3.5 w-3.5 text-success" />,
    error: <XCircle className="h-3.5 w-3.5 text-destructive" />,
  }[call.status];

  const chevron = expanded
    ? <ChevronDown className="h-3 w-3 text-muted-foreground" />
    : <ChevronRight className="h-3 w-3 text-muted-foreground" />;

  return (
    <div className="overflow-hidden rounded-md border bg-card text-sm">
      <button
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left transition-colors hover:bg-muted/60"
        onClick={() => setExpanded(!expanded)}
        title={t("Tool call", "工具调用")}
      >
        {statusIcon}
        <span className="flex-1 font-mono text-xs font-medium text-foreground">{call.tool}</span>
        {chevron}
      </button>

      {expanded && (
        <div className="px-3 pb-3 flex flex-col gap-2">
          {call.input && (
            <JsonViewer data={call.input} title={t("Input", "输入")} />
          )}
          {call.output !== undefined && (
            <JsonViewer data={call.output} title={t("Output", "输出")} />
          )}
          {call.error && (
            <p className="text-xs text-destructive font-mono">{call.error}</p>
          )}
        </div>
      )}
    </div>
  );
}
