"use client";

import { fmtETTime, num } from "./api";

export interface Candle {
  ts: string;
  o: number;
  h: number;
  l: number;
  c: number;
}

const GREEN = "#34d399";
const RED = "#f87171";

export function CandleChart({ symbol, data }: { symbol: string; data: Candle[] }) {
  if (data.length < 2) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-slate-600">
        Press{" "}
        <span className="mx-1 rounded bg-slate-800 px-1.5 py-0.5 font-mono text-slate-300">
          Start
        </span>{" "}
        to open {symbol} and watch candles print.
      </div>
    );
  }

  // Keep the most recent window so candles stay legible on long days.
  const MAX = 180;
  const rows = data.length > MAX ? data.slice(data.length - MAX) : data;
  const n = rows.length;

  const lo = Math.min(...rows.map((r) => r.l));
  const hi = Math.max(...rows.map((r) => r.h));
  const pad = (hi - lo) * 0.06 || 1;
  const min = lo - pad;
  const max = hi + pad;

  const SLOT = 6;
  const VW = n * SLOT;
  const VH = 100;
  const y = (p: number) => ((max - p) / (max - min)) * VH;

  const gridlines = [0, 0.25, 0.5, 0.75, 1].map((f) => ({
    top: `${f * 100}%`,
    price: max - f * (max - min),
  }));

  const last = rows[rows.length - 1];
  const lastUp = last.c >= last.o;

  return (
    <div className="relative h-full w-full overflow-hidden">
      {/* price gridlines + labels */}
      {gridlines.map((g, i) => (
        <div key={i} className="pointer-events-none absolute inset-x-0" style={{ top: g.top }}>
          <div className="border-t border-slate-800/70" />
          <div className="absolute right-1 -translate-y-1/2 bg-slate-950/70 px-1 font-mono text-[10px] text-slate-500">
            {num(g.price)}
          </div>
        </div>
      ))}

      <svg
        viewBox={`0 0 ${VW} ${VH}`}
        preserveAspectRatio="none"
        className="absolute inset-0 h-full w-full"
      >
        {rows.map((r, i) => {
          const cx = i * SLOT + SLOT / 2;
          const up = r.c >= r.o;
          const color = up ? GREEN : RED;
          const yO = y(r.o);
          const yC = y(r.c);
          const top = Math.min(yO, yC);
          const bodyH = Math.max(Math.abs(yO - yC), 0.4);
          return (
            <g key={i}>
              <line x1={cx} x2={cx} y1={y(r.h)} y2={y(r.l)} stroke={color} strokeWidth={0.5} />
              <rect x={cx - 2} y={top} width={4} height={bodyH} fill={color} />
            </g>
          );
        })}
      </svg>

      {/* last price marker */}
      <div
        className="pointer-events-none absolute right-0 -translate-y-1/2"
        style={{ top: `${y(last.c)}%` }}
      >
        <span
          className="rounded-l px-1 font-mono text-[10px] font-bold text-slate-950"
          style={{ background: lastUp ? GREEN : RED }}
        >
          {num(last.c)}
        </span>
      </div>

      {/* time axis */}
      <div className="pointer-events-none absolute bottom-0 left-0 flex w-full justify-between px-1 font-mono text-[10px] text-slate-600">
        <span>{fmtETTime(rows[0].ts)}</span>
        <span>{fmtETTime(rows[Math.floor(n / 2)].ts)}</span>
        <span>{fmtETTime(last.ts)}</span>
      </div>
    </div>
  );
}
