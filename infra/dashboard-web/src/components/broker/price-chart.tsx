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
  const color = up ? "#34d399" : "#f87171";
  return (
    <div className="h-full w-full">
      {data.length < 2 ? (
        <div className="flex h-full items-center justify-center text-sm text-slate-600">
          Press{" "}
          <span className="mx-1 rounded bg-slate-800 px-1.5 py-0.5 font-mono text-slate-300">
            Start
          </span>{" "}
          to open {symbol} and watch the tape build.
        </div>
      ) : (
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="pxfill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity={0.35} />
                <stop offset="100%" stopColor={color} stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="ts"
              tickFormatter={fmtETTime}
              tick={{ fill: "#64748b", fontSize: 10 }}
              minTickGap={48}
              axisLine={{ stroke: "#1e293b" }}
              tickLine={false}
            />
            <YAxis
              domain={["auto", "auto"]}
              tick={{ fill: "#64748b", fontSize: 10 }}
              width={52}
              tickFormatter={(v) => num(v, 2)}
              axisLine={false}
              tickLine={false}
              orientation="right"
            />
            <Tooltip
              contentStyle={{
                background: "#0f172a",
                border: "1px solid #334155",
                borderRadius: 8,
                fontSize: 12,
              }}
              labelStyle={{ color: "#94a3b8" }}
              labelFormatter={(l) => fmtETTime(String(l))}
              formatter={(v: number) => [num(v, 2), symbol]}
            />
            <Area
              type="monotone"
              dataKey="price"
              stroke={color}
              strokeWidth={2}
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
