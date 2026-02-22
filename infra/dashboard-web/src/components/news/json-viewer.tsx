"use client";

import React, { useState } from "react";
import { Check, Copy } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

interface JsonViewerProps {
  data: any;
  title?: string;
}

export function JsonViewer({ data, title }: JsonViewerProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    void navigator.clipboard.writeText(JSON.stringify(data, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (!data) return null;

  return (
    <div className="group relative overflow-hidden rounded-lg border bg-zinc-950">
      <div className="flex items-center justify-between border-b border-white/10 bg-white/5 px-3 py-1.5">
        <span className="text-[10px] font-bold uppercase tracking-wider text-zinc-400">{title || "JSON"}</span>
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6 text-zinc-400 hover:bg-white/10 hover:text-white"
          onClick={handleCopy}
        >
          {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
        </Button>
      </div>
      <div className="max-h-80 overflow-auto p-3 scrollbar-thin scrollbar-thumb-white/10">
        <pre className="font-mono text-[11px] leading-relaxed">
          {formatJson(data)}
        </pre>
      </div>
    </div>
  );
}

function formatJson(obj: any) {
  const json = JSON.stringify(obj, null, 2);
  
  return json.split("\n").map((line, i) => {
    const keyMatch = line.match(/^(\s*)"([^"]+)":/);
    if (keyMatch) {
      const indent = keyMatch[1];
      const key = keyMatch[2];
      const rest = line.slice(keyMatch[0].length);
      return (
        <div key={i} className="min-h-[1.2em]">
          {indent}
          <span className="text-sky-400">"{key}"</span>:
          {formatValue(rest)}
        </div>
      );
    }
    return <div key={i} className="min-h-[1.2em]">{formatValue(line)}</div>;
  });
}

function formatValue(val: string) {
  if (val.includes('"')) {
    return <span className="text-amber-200">{val}</span>;
  }
  if (val.match(/\d+/)) {
    return <span className="text-indigo-300">{val}</span>;
  }
  if (val.includes("true") || val.includes("false") || val.includes("null")) {
    return <span className="text-rose-300">{val}</span>;
  }
  return <span className="text-zinc-300">{val}</span>;
}
