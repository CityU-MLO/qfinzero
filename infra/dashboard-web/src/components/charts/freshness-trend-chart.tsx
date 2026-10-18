"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { chart } from "@/lib/chart-theme";

export function FreshnessTrendChart({
  data,
}: {
  data: Array<{ service: string; minutesBehind: number }>;
}) {
  if (data.length === 0) {
    return (
      <div className="flex h-48 w-full items-center justify-center rounded-lg border border-dashed">
        <p className="text-sm text-muted-foreground">No freshness data yet.</p>
      </div>
    );
  }

  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 10, left: 10, right: 10, bottom: 20 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={chart.grid} />
          <XAxis 
            dataKey="service" 
            tick={chart.tick} 
            axisLine={false}
            tickLine={false}
            dy={10}
          />
          <YAxis 
            tick={chart.tick} 
            unit="ms" 
            axisLine={false}
            tickLine={false}
            width={80}
          />
          <Tooltip 
            cursor={{ fill: chart.primaryFill }}
            contentStyle={chart.tooltip.contentStyle}
            formatter={(value: number) => [`${value} ms`, "Lag"]} 
          />
          <Bar 
            dataKey="minutesBehind" 
            fill={chart.primary} 
            radius={[2, 2, 0, 0]} 
            barSize={40}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
