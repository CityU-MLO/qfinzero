"use client";

import { buildCoverageHeatmap } from "@/lib/coverage";

export function CoverageHeatmap({
  title,
  dailyCounts,
  start,
  end,
}: {
  title: string;
  dailyCounts: Array<{ date: string; count: number }>;
  start: string | null;
  end: string | null;
}) {
  const cells = buildCoverageHeatmap(dailyCounts, start, end);
  const max = Math.max(1, ...cells.map((cell) => cell.count));

  return (
    <div className="space-y-2 rounded-xl border bg-white/80 p-4">
      <h4 className="text-sm font-semibold">{title}</h4>
      <div className="grid grid-cols-14 gap-1">
        {cells.map((cell) => {
          const intensity = Math.min(1, cell.count / max);
          const alpha = 0.12 + intensity * 0.68;
          return (
            <div
              key={cell.date}
              title={`${cell.date}: ${cell.count}`}
              className="h-4 rounded-sm"
              style={{ backgroundColor: `rgba(14,116,144,${alpha})` }}
            />
          );
        })}
      </div>
      <p className="text-xs text-muted-foreground">{cells.length} days shown</p>
    </div>
  );
}
