"use client";

import { Play, Pause, SkipForward, Rewind, Radio } from "lucide-react";

import { fmtET, type Clock } from "./api";

const SPEEDS = [1, 2, 5, 10, 30, 60];

export function ClockBar({
  clock,
  started,
  playing,
  speed,
  onStart,
  onPlayPause,
  onStepOne,
  onSpeed,
  onScrub,
  scrubbing,
}: {
  clock: Clock | null;
  started: boolean;
  playing: boolean;
  speed: number;
  onStart: () => void;
  onPlayPause: () => void;
  onStepOne: () => void;
  onSpeed: (n: number) => void;
  onScrub: (index: number) => void;
  scrubbing: boolean;
}) {
  const total = clock?.total_bars ?? 0;
  const index = clock?.index ?? -1;
  const done = clock?.is_done ?? false;
  const speedIdx = Math.max(0, SPEEDS.indexOf(speed));

  return (
    <div className="flex flex-wrap items-center gap-4 border-t border-slate-800 bg-slate-950/80 px-5 py-3">
      {/* Transport */}
      <div className="flex items-center gap-2">
        {!started ? (
          <button
            onClick={onStart}
            className="flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-bold text-slate-950 transition hover:bg-emerald-400"
          >
            <Radio className="h-4 w-4" /> Open market
          </button>
        ) : (
          <>
            <button
              onClick={onPlayPause}
              disabled={done}
              className="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-800 text-white transition hover:bg-slate-700 disabled:opacity-40"
              title={playing ? "Pause" : "Play"}
            >
              {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            </button>
            <button
              onClick={onStepOne}
              disabled={playing || done}
              className="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-800 text-white transition hover:bg-slate-700 disabled:opacity-40"
              title="Step one minute"
            >
              <SkipForward className="h-4 w-4" />
            </button>
          </>
        )}
      </div>

      {/* Scrubber */}
      <div className="flex min-w-[220px] flex-1 items-center gap-3">
        <Rewind className="h-4 w-4 shrink-0 text-slate-500" />
        <input
          type="range"
          min={0}
          max={Math.max(0, total - 1)}
          value={Math.max(0, index)}
          onChange={(e) => onScrub(Number(e.target.value))}
          disabled={!started}
          className="broker-range h-1.5 w-full cursor-pointer appearance-none rounded-full bg-slate-700 accent-sky-400 disabled:opacity-40"
        />
        <span className="w-16 shrink-0 text-right font-mono text-xs text-slate-500">
          {Math.max(0, index) + 1}/{total || "—"}
        </span>
      </div>

      {/* Clock readout */}
      <div className="flex items-center gap-2 font-mono text-sm">
        <span className={playing ? "h-2 w-2 animate-pulse rounded-full bg-emerald-400" : "h-2 w-2 rounded-full bg-slate-600"} />
        <span className="text-white">{clock ? fmtET(clock.current_ts) : "—"}</span>
        <span className="text-slate-500">ET</span>
        {done && <span className="rounded bg-slate-800 px-1.5 py-0.5 text-xs text-amber-400">CLOSED</span>}
        {scrubbing && <span className="text-xs text-sky-400">rewinding…</span>}
      </div>

      {/* Speed */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-slate-500">Speed</span>
        <input
          type="range"
          min={0}
          max={SPEEDS.length - 1}
          value={speedIdx}
          onChange={(e) => onSpeed(SPEEDS[Number(e.target.value)])}
          className="broker-range h-1.5 w-24 cursor-pointer appearance-none rounded-full bg-slate-700 accent-emerald-400"
        />
        <span className="w-12 font-mono text-sm font-bold text-emerald-400">{speed}×</span>
      </div>
    </div>
  );
}
