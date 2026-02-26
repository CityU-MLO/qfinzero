"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Loader2, CheckCircle2, XCircle } from "lucide-react";
import { JsonViewer } from "@/components/news/json-viewer";

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
  const [expanded, setExpanded] = useState(false);

  const statusIcon = {
    loading: <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-500" />,
    done: <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />,
    error: <XCircle className="h-3.5 w-3.5 text-rose-500" />,
  }[call.status];

  const chevron = expanded
    ? <ChevronDown className="h-3 w-3 text-muted-foreground" />
    : <ChevronRight className="h-3 w-3 text-muted-foreground" />;

  return (
    <div className="rounded-lg border bg-zinc-50 text-sm overflow-hidden">
      <button
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-zinc-100 transition-colors text-left"
        onClick={() => setExpanded(!expanded)}
      >
        {statusIcon}
        <span className="font-mono text-xs font-semibold text-zinc-700 flex-1">{call.tool}</span>
        {chevron}
      </button>

      {expanded && (
        <div className="px-3 pb-3 flex flex-col gap-2">
          {call.input && (
            <JsonViewer data={call.input} title="Input" />
          )}
          {call.output !== undefined && (
            <JsonViewer data={call.output} title="Output" />
          )}
          {call.error && (
            <p className="text-xs text-rose-500 font-mono">{call.error}</p>
          )}
        </div>
      )}
    </div>
  );
}
