"use client";

import { Wallet, LineChart, ArrowRight } from "lucide-react";

export function Landing({
  onAllocate,
  onEnter,
}: {
  onAllocate: () => void;
  onEnter: () => void;
}) {
  return (
    <div className="flex min-h-full flex-col items-center justify-center px-6 py-16">
      <div className="mb-2 text-xs font-semibold uppercase tracking-[0.35em] text-emerald-400/80">
        QFinZero
      </div>
      <h1 className="mb-3 text-center text-5xl font-black tracking-tight text-white">
        Paper&nbsp;Money&nbsp;Broker
      </h1>
      <p className="mb-12 max-w-xl text-center text-base text-slate-400">
        A real broker terminal for agents and humans — trade live against real
        historical market data, minute by minute, with a clock you control.
      </p>

      <div className="grid w-full max-w-3xl gap-5 sm:grid-cols-2">
        <button
          onClick={onAllocate}
          className="group relative flex flex-col items-start gap-3 rounded-2xl border border-slate-700 bg-slate-900/60 p-7 text-left transition hover:border-emerald-500 hover:bg-slate-900"
        >
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-400">
            <Wallet className="h-6 w-6" />
          </div>
          <div className="text-xl font-bold text-white">Allocate Account</div>
          <p className="text-sm text-slate-400">
            Open a new brokerage account. Set starting capital, market, fees and
            margin — the detailed settings your strategy needs.
          </p>
          <span className="mt-2 flex items-center gap-1 text-sm font-semibold text-emerald-400">
            Set up <ArrowRight className="h-4 w-4 transition group-hover:translate-x-1" />
          </span>
        </button>

        <button
          onClick={onEnter}
          className="group relative flex flex-col items-start gap-3 rounded-2xl border border-slate-700 bg-slate-900/60 p-7 text-left transition hover:border-sky-500 hover:bg-slate-900"
        >
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-sky-500/15 text-sky-400">
            <LineChart className="h-6 w-6" />
          </div>
          <div className="text-xl font-bold text-white">Enter Account</div>
          <p className="text-sm text-slate-400">
            Step onto the trading floor. Pick an account and a start date, then
            open the market and trade the tape in real time.
          </p>
          <span className="mt-2 flex items-center gap-1 text-sm font-semibold text-sky-400">
            Start trading <ArrowRight className="h-4 w-4 transition group-hover:translate-x-1" />
          </span>
        </button>
      </div>
    </div>
  );
}
