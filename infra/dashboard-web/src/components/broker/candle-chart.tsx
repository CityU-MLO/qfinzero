"use client";

import { fmtETTime, num } from "./api";

export interface Candle {
  ts: string;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

const GREEN = "#34d399";
const RED = "#f87171";
const MA_FAST = "#fbbf24"; // MA5  — amber
const MA_SLOW = "#38bdf8"; // MA20 — sky

function sma(vals: number[], period: number): (number | null)[] {
  const out: (number | null)[] = [];
  let sum = 0;
  for (let i = 0; i < vals.length; i++) {
    sum += vals[i];
    if (i >= period) sum -= vals[i - period];
    out.push(i >= period - 1 ? sum / period : null);
  }
  return out;
}

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

  const MAX = 180;
  const rows = data.length > MAX ? data.slice(data.length - MAX) : data;
  const n = rows.length;

  const closes = rows.map((r) => r.c);
  const ma5 = sma(closes, 5);
  const ma20 = sma(closes, 20);

  const lo = Math.min(...rows.map((r) => r.l));
  const hi = Math.max(...rows.map((r) => r.h));
  const pad = (hi - lo) * 0.06 || 1;
  const min = lo - pad;
  const max = hi + pad;
  const volMax = Math.max(...rows.map((r) => r.v), 1);

  const SLOT = 6;
  const VW = n * SLOT;
  const VH = 100;
  const P_TOP = 3;
  const P_BOT = 72;
  const V_TOP = 80;
  const V_BOT = 99;
  const yP = (p: number) => P_TOP + ((max - p) / (max - min)) * (P_BOT - P_TOP);
  const yV = (v: number) => V_BOT - (v / volMax) * (V_BOT - V_TOP);

  const gridlines = [0, 0.25, 0.5, 0.75, 1].map((f) => ({
    top: `${(P_TOP + f * (P_BOT - P_TOP)) / VH * 100}%`,
    price: max - f * (max - min),
  }));

  const last = rows[rows.length - 1];
  const lastUp = last.c >= last.o;

  const maPath = (ma: (number | null)[]) => {
    let d = "";
    ma.forEach((m, i) => {
      if (m == null) return;
      const x = i * SLOT + SLOT / 2;
      d += `${d ? "L" : "M"}${x.toFixed(2)} ${yP(m).toFixed(2)} `;
    });
    return d.trim();
  };

  const legend = (label: string, color: string, val: number | null) => (
    <span style={{ color }} className="font-mono">
      {label} {val != null ? num(val) : "—"}
    </span>
  );

  return (
    <div className="relative h-full w-full overflow-hidden">
      {/* indicator legend */}
      <div className="pointer-events-none absolute left-1 top-1 z-10 flex gap-3 text-[10px]">
        {legend("MA5", MA_FAST, ma5[ma5.length - 1])}
        {legend("MA20", MA_SLOW, ma20[ma20.length - 1])}
        <span className="font-mono text-slate-500">VOL {last.v.toLocaleString()}</span>
      </div>

      {/* price gridlines + labels */}
      {gridlines.map((g, i) => (
        <div key={i} className="pointer-events-none absolute inset-x-0" style={{ top: g.top }}>
          <div className="border-t border-slate-800/70" />
          <div className="absolute right-1 -translate-y-1/2 bg-slate-950/70 px-1 font-mono text-[10px] text-slate-500">
            {num(g.price)}
          </div>
        </div>
      ))}

      <svg viewBox={`0 0 ${VW} ${VH}`} preserveAspectRatio="none" className="absolute inset-0 h-full w-full">
        {/* volume */}
        {rows.map((r, i) => {
          const cx = i * SLOT + SLOT / 2;
          const up = r.c >= r.o;
          return (
            <rect
              key={`v${i}`}
              x={cx - 2}
              y={yV(r.v)}
              width={4}
              height={Math.max(V_BOT - yV(r.v), 0.3)}
              fill={up ? GREEN : RED}
              opacity={0.4}
            />
          );
        })}
        {/* candles */}
        {rows.map((r, i) => {
          const cx = i * SLOT + SLOT / 2;
          const up = r.c >= r.o;
          const color = up ? GREEN : RED;
          const yO = yP(r.o);
          const yC = yP(r.c);
          return (
            <g key={i}>
              <line x1={cx} x2={cx} y1={yP(r.h)} y2={yP(r.l)} stroke={color} strokeWidth={0.5} />
              <rect x={cx - 2} y={Math.min(yO, yC)} width={4} height={Math.max(Math.abs(yO - yC), 0.4)} fill={color} />
            </g>
          );
        })}
        {/* moving averages */}
        <path d={maPath(ma5)} fill="none" stroke={MA_FAST} strokeWidth={0.6} />
        <path d={maPath(ma20)} fill="none" stroke={MA_SLOW} strokeWidth={0.6} />
      </svg>

      {/* last price marker */}
      <div className="pointer-events-none absolute right-0 -translate-y-1/2" style={{ top: `${(yP(last.c) / VH) * 100}%` }}>
        <span className="rounded-l px-1 font-mono text-[10px] font-bold text-slate-950" style={{ background: lastUp ? GREEN : RED }}>
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
