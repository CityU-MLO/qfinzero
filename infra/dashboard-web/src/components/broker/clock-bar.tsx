"use client";

import { Play, Pause, SkipForward, Rewind, Radio } from "lucide-react";

import { fmtET, type Clock, type Segment } from "./api";

import { useT } from "@/components/locale-provider";

const SPEEDS = [1, 2, 5, 10, 30, 60];

export const SEGMENT_LABEL: Record<Segment, [string, string]> = {
  OVERNIGHT: ["Overnight", "夜盘"], PRE: ["Pre-market", "盘前"], REGULAR: ["Regular", "盘中"], POST: ["After-hours", "盘后"],
};
// the same depth order as the chart's session bands (overnight deepest, regular unshaded)
const SEGMENT_TONE: Record<Segment, string> = {
  OVERNIGHT: "bg-foreground/[0.14] text-foreground", PRE: "bg-foreground/[0.09] text-foreground",
  REGULAR: "bg-up/15 text-up", POST: "bg-foreground/[0.06] text-foreground",
};

/** Where the session can start: the segments the day's timeline has, in time order. */
export type StartPoint = "OVERNIGHT" | "PRE" | "REGULAR";

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
  starts = ["REGULAR"],
}: {
  clock: Clock | null;
  started: boolean;
  playing: boolean;
  speed: number;
  onStart: (at: StartPoint) => void;
  /** start points offered (REGULAR = the 09:30 ET open) */
  starts?: StartPoint[];
  onPlayPause: () => void;
  onStepOne: () => void;
  onSpeed: (n: number) => void;
  onScrub: (index: number) => void;
  scrubbing: boolean;
}) {
  const t = useT();
  const total = clock?.total_bars ?? 0;
  const index = clock?.index ?? -1;
  const done = clock?.is_done ?? false;
  const speedIdx = Math.max(0, SPEEDS.indexOf(speed));

  return (
    <div className="broker-statusbar flex flex-wrap items-center gap-4 border-t border-border bg-background px-5 py-3">
      {/* Transport */}
      <div className="flex items-center gap-2">
        {!started ? (
          <>
            <button
              onClick={() => onStart("REGULAR")}
              className="flex items-center gap-2 rounded-lg bg-up px-4 py-2 text-sm font-semibold text-white transition hover:bg-up/90"
            >
              <Radio className="h-4 w-4" /> {t("Open market", "开盘")}
            </button>
            {starts.filter((s) => s !== "REGULAR").map((s) => (
              <button key={s} onClick={() => onStart(s)}
                      title={s === "OVERNIGHT" ? t("Start at 20:00 ET the evening before (Blue Ocean)", "从前一晚美东 20:00 开始（Blue Ocean）")
                        : t("Start at 04:00 ET", "从美东 04:00 开始")}
                      className="rounded-lg border border-border px-3 py-2 text-xs font-medium text-foreground transition hover:bg-accent">
                {s === "OVERNIGHT" ? t("From overnight", "从夜盘开始") : t("From pre-market", "从盘前开始")}
              </button>
            ))}
          </>
        ) : (
          <>
            <button
              onClick={onPlayPause}
              disabled={done}
              className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted text-foreground transition hover:bg-accent disabled:opacity-40"
              title={playing ? t("Pause", "暂停") : t("Play", "播放")}
            >
              {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            </button>
            <button
              onClick={onStepOne}
              disabled={playing || done}
              className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted text-foreground transition hover:bg-accent disabled:opacity-40"
              title={t("Step one minute", "前进一分钟")}
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
        {clock?.segment && (
          <span className={`rounded px-1.5 py-0.5 font-sans text-[11px] font-medium ${SEGMENT_TONE[clock.segment]}`}
                title={clock.trading_date ? t(`Trading date ${clock.trading_date}`, `交易日 ${clock.trading_date}`) : undefined}>
            {t(...SEGMENT_LABEL[clock.segment])}
          </span>
        )}
        {done && <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-warning">{t("CLOSED", "已收盘")}</span>}
        {scrubbing && <span className="text-xs text-primary">{t("rewinding…", "回溯中…")}</span>}
      </div>

      {/* Speed */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground">{t("Speed", "速度")}</span>
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
