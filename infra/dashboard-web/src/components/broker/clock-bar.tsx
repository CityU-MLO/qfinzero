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
    <div className="broker-statusbar flex flex-wrap items-center gap-4 border-t border-border bg-background px-5 py-3">
      {/* Transport */}
      <div className="flex items-center gap-2">
        {!started ? (
          <button
            onClick={onStart}
            className="flex items-center gap-2 rounded-lg bg-up px-4 py-2 text-sm font-semibold text-white transition hover:bg-up/90"
          >
            <Radio className="h-4 w-4" /> Open market
          </button>
        ) : (
          <>
            <button
              onClick={onPlayPause}
              disabled={done}
              className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted text-foreground transition hover:bg-accent disabled:opacity-40"
              title={playing ? "Pause" : "Play"}
            >
              {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            </button>
            <button
              onClick={onStepOne}
              disabled={playing || done}
              className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted text-foreground transition hover:bg-accent disabled:opacity-40"
              title="Step one minute"
            >
              <SkipForward className="h-4 w-4" />
            </button>
          </>
        )}
      </div>

      {/* Scrubber */}
      <div className="flex min-w-[220px] flex-1 items-center gap-3">
        <Rewind className="h-4 w-4 shrink-0 text-muted-foreground" />
        <input
          type="range"
          min={0}
          max={Math.max(0, total - 1)}
          value={Math.max(0, index)}
          onChange={(e) => onScrub(Number(e.target.value))}
          disabled={!started}
          className="broker-range h-1.5 w-full cursor-pointer appearance-none rounded-full bg-secondary accent-primary disabled:opacity-40"
        />
        <span className="w-16 shrink-0 text-right font-mono text-xs text-muted-foreground">
          {Math.max(0, index) + 1}/{total || "—"}
        </span>
      </div>

      {/* Clock readout */}
      <div className="flex items-center gap-2 font-mono text-sm">
        <span className={playing ? "h-2 w-2 animate-pulse rounded-full bg-up" : "h-2 w-2 rounded-full bg-muted-foreground/30"} />
        <span className="text-foreground">{clock ? fmtET(clock.current_ts) : "—"}</span>
        <span className="text-muted-foreground">ET</span>
        {done && <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-warning">CLOSED</span>}
        {scrubbing && <span className="text-xs text-primary">rewinding…</span>}
      </div>

      {/* Speed */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground">Speed</span>
        <input
          type="range"
          min={0}
          max={SPEEDS.length - 1}
          value={speedIdx}
          onChange={(e) => onSpeed(SPEEDS[Number(e.target.value)])}
          className="broker-range h-1.5 w-24 cursor-pointer appearance-none rounded-full bg-secondary accent-primary"
        />
        <span className="w-12 font-mono text-sm font-semibold text-up">{speed}×</span>
      </div>
    </div>
  );
}
