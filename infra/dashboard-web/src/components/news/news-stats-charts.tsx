"use client";

import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { chart } from "@/lib/chart-theme";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { NewsStatsResponse } from "@/lib/types";
import { useT } from "@/components/locale-provider";

export function NewsStatsCharts({ stats }: { stats: NewsStatsResponse | null }) {
  const t = useT();
  if (!stats) {
    return null;
  }

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="overflow-hidden">
        <CardHeader>
          <CardTitle>{t("Daily News Volume Trend", "每日新闻量趋势")}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={stats.daily_counts} margin={{ left: -20, right: 10 }}>
                <CartesianGrid vertical={false} strokeDasharray="3 3" stroke={chart.grid} />
                <XAxis 
                  dataKey="date" 
                  tick={chart.tick} 
                  axisLine={false}
                  tickLine={false}
                  dy={10}
                />
                <YAxis 
                  tick={chart.tick} 
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip 
                  contentStyle={chart.tooltip.contentStyle}
                />
                <Line 
                  type="monotone" 
                  dataKey="count" 
                  name={t("Articles", "文章数")}
                  stroke={chart.primary}
                  strokeWidth={1.5}
                  dot={false}
                  activeDot={{ r: 4, strokeWidth: 0 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <Card className="overflow-hidden">
        <CardHeader>
          <CardTitle>{t("Top Tickers by News Volume", "新闻量最多的代码")}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart 
                data={stats.top_tickers.slice(0, 10)} 
                layout="vertical" 
                margin={{ left: 10, right: 20 }}
              >
                <CartesianGrid horizontal={false} strokeDasharray="3 3" stroke={chart.grid} />
                <XAxis type="number" hide />
                <YAxis 
                  dataKey="ticker" 
                  type="category" 
                  width={80} 
                  tick={{ ...chart.tick, fill: "hsl(var(--foreground))" }} 
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip 
                  cursor={{ fill: chart.primaryFill }}
                  contentStyle={chart.tooltip.contentStyle}
                />
                <Bar 
                  dataKey="count" 
                  name={t("Articles", "文章数")}
                  fill={chart.primary} 
                  radius={[0, 2, 2, 0]} 
                  barSize={14}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
