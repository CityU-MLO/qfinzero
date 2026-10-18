"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

/** A small set of mutually exclusive options shown as joined buttons. */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  className,
}: {
  value: T;
  onChange: (v: T) => void;
  options: readonly { value: T; label: React.ReactNode; icon?: React.ComponentType<{ className?: string }> }[];
  className?: string;
}) {
  return (
    <div role="radiogroup" className={cn("inline-flex rounded-md border bg-card p-0.5", className)}>
      {options.map((o) => {
        const active = o.value === value;
        const Icon = o.icon;
        return (
          <button key={o.value} type="button" role="radio" aria-checked={active} onClick={() => onChange(o.value)}
            className={cn("inline-flex items-center gap-1.5 rounded-sm px-2.5 py-1 text-[13px] font-medium transition-colors",
              active ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground")}>
            {Icon && <Icon className="h-3.5 w-3.5" />}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
