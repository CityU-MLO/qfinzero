"use client";

import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { NewsStatsResponse } from "@/lib/types";

export function NewsStatsCharts({ stats }: { stats: NewsStatsResponse | null }) {
  if (!stats) {
    return null;
  }

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="overflow-hidden shadow-sm">
        <CardHeader className="bg-muted/20 pb-3">
          <CardTitle className="text-sm font-semibold tracking-tight">Daily News Volume Trend</CardTitle>
        </CardHeader>
        <CardContent className="pt-6">
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={stats.daily_counts} margin={{ left: -20, right: 10 }}>
                <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis 
                  dataKey="date" 
                  tick={{ fontSize: 11, fill: "#64748b" }} 
                  axisLine={false}
                  tickLine={false}
                  dy={10}
                />
                <YAxis 
                  tick={{ fontSize: 11, fill: "#64748b" }} 
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip 
                  contentStyle={{ borderRadius: "8px", border: "1px solid #e2e8f0", boxShadow: "0 4px 6px -1px rgb(0 0 0 / 0.1)" }}
                />
                <Line 
                  type="monotone" 
                  dataKey="count" 
                  stroke="#0e7490" 
                  strokeWidth={2.5}
                  dot={{ r: 4, fill: "#0e7490", strokeWidth: 2, stroke: "#fff" }}
                  activeDot={{ r: 6, strokeWidth: 0 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <Card className="overflow-hidden shadow-sm">
        <CardHeader className="bg-muted/20 pb-3">
          <CardTitle className="text-sm font-semibold tracking-tight">Top Tickers by News Volume</CardTitle>
        </CardHeader>
        <CardContent className="pt-6">
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart 
                data={stats.top_tickers.slice(0, 10)} 
                layout="vertical" 
                margin={{ left: 10, right: 20 }}
              >
                <CartesianGrid horizontal={false} strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis type="number" hide />
                <YAxis 
                  dataKey="ticker" 
                  type="category" 
                  width={80} 
                  tick={{ fontSize: 11, fontWeight: 600, fill: "#334155" }} 
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip 
                  cursor={{ fill: "#f8fafc" }}
                  contentStyle={{ borderRadius: "8px", border: "1px solid #e2e8f0", boxShadow: "0 4px 6px -1px rgb(0 0 0 / 0.1)" }}
                />
                <Bar 
                  dataKey="count" 
                  fill="#f59e0b" 
                  radius={[0, 4, 4, 0]} 
                  barSize={24}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
