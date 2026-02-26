"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

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
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f0f0f0" />
          <XAxis 
            dataKey="service" 
            tick={{ fontSize: 12, fontWeight: 500 }} 
            axisLine={false}
            tickLine={false}
            dy={10}
          />
          <YAxis 
            tick={{ fontSize: 12 }} 
            unit="ms" 
            axisLine={false}
            tickLine={false}
            width={80}
          />
          <Tooltip 
            cursor={{ fill: "#f8fafc" }}
            contentStyle={{ borderRadius: "8px", border: "1px solid #e2e8f0", boxShadow: "0 4px 6px -1px rgb(0 0 0 / 0.1)" }}
            formatter={(value: number) => [`${value} ms`, "Lag"]} 
          />
          <Bar 
            dataKey="minutesBehind" 
            fill="#0891b2" 
            radius={[4, 4, 0, 0]} 
            barSize={40}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
