"use client";

import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { fmtETTime, num } from "./api";

import { chart } from "@/lib/chart-theme";

export interface PricePoint {
  ts: string;
  price: number;
}

export function PriceChart({
  symbol,
  data,
  up,
}: {
  symbol: string;
  data: PricePoint[];
  up: boolean;
}) {
  const color = up ? chart.up : chart.down;
  return (
    <div className="h-full w-full">
      {data.length < 2 ? (
        <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
          Press{" "}
          <span className="mx-1 rounded bg-muted px-1.5 py-0.5 font-mono text-foreground">
            Start
          </span>{" "}
          to open {symbol} and watch the tape build.
        </div>
      ) : (
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="pxfill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity={0.18} />
                <stop offset="100%" stopColor={color} stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="ts"
              tickFormatter={fmtETTime}
              tick={chart.tick}
              minTickGap={48}
              axisLine={{ stroke: chart.grid }}
              tickLine={false}
            />
            <YAxis
              domain={["auto", "auto"]}
              tick={chart.tick}
              width={52}
              tickFormatter={(v) => num(v, 2)}
              axisLine={false}
              tickLine={false}
              orientation="right"
            />
            <Tooltip
              contentStyle={chart.tooltip.contentStyle}
              labelStyle={chart.tooltip.labelStyle}
              labelFormatter={(l) => fmtETTime(String(l))}
              formatter={(v: number) => [num(v, 2), symbol]}
            />
            <Area
              type="monotone"
              dataKey="price"
              stroke={color}
              strokeWidth={1.5}
              fill="url(#pxfill)"
              isAnimationActive={false}
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
