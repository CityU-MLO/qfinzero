"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";

import { sessionOptionChain, num, type ChainResponse, type ChainLeg } from "./api";

export function OptionChain({
  sessionId,
  underlying,
  clockIndex,
  onTrade,
}: {
  sessionId: string;
  underlying: string;
  clockIndex: number;
  onTrade: (contract: string, side: "BUY" | "SELL") => void;
}) {
  const [chain, setChain] = useState<ChainResponse | null>(null);
  const [expiry, setExpiry] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const busyRef = useRef(false);
  const prevLast = useRef<Record<string, number>>({});
  const [flash, setFlash] = useState<Record<string, "up" | "down">>({});

  // Re-fetch on underlying/expiry change and every clock step (flash). Skips if a
  // request is in flight, so it self-throttles to backend latency.
  useEffect(() => {
    let cancelled = false;
    if (busyRef.current) return;
    busyRef.current = true;
    if (!chain) setLoading(true);
    sessionOptionChain(sessionId, underlying, expiry || undefined)
      .then((c) => {
        if (cancelled) return;
        // compute per-contract flash direction vs the previous fetch
        const f: Record<string, "up" | "down"> = {};
        for (const row of c.rows) {
          for (const leg of [row.call, row.put]) {
            if (!leg?.contract || leg.last == null) continue;
            const p = prevLast.current[leg.contract];
            if (p != null && leg.last !== p) f[leg.contract] = leg.last > p ? "up" : "down";
            prevLast.current[leg.contract] = leg.last;
          }
        }
        setFlash(f);
        setChain(c);
        if (!expiry && c.expiry) setExpiry(c.expiry);
        setErr(null);
      })
      .catch((e) => !cancelled && setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => {
        busyRef.current = false;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, underlying, expiry, clockIndex]);

  const rows = chain?.rows ?? [];
  const spot = chain?.spot ?? undefined;
  const atmStrike =
    spot != null && rows.length
      ? rows.reduce((b, r) => (Math.abs(r.strike - spot) < Math.abs(b.strike - spot) ? r : b)).strike
      : null;

  return (
    <div className="broker-panel flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-3 border-b border-slate-800 px-4 py-2">
        <div className="text-sm font-bold text-white">
          {underlying} <span className="text-slate-500">options</span>
        </div>
        <select
          value={expiry}
          onChange={(e) => {
            setExpiry(e.target.value);
            setChain(null);
          }}
          className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-white"
        >
          {(chain?.expiries ?? []).map((x) => (
            <option key={x} value={x}>
              exp {x}
            </option>
          ))}
        </select>
        {spot != null && (
          <span className="font-mono text-xs text-slate-400">
            spot <span className="text-white">{num(spot)}</span>
          </span>
        )}
        <span className="flex items-center gap-1 text-[11px] text-emerald-400">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" /> live · minute
        </span>
        {loading && <Loader2 className="h-4 w-4 animate-spin text-slate-400" />}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto font-mono text-xs">
        {err && <div className="p-4 text-red-400">{err}</div>}
        {!err && !rows.length && !loading && (
          <div className="p-6 text-center text-slate-600">No chain for this underlying/date.</div>
        )}
        {!!rows.length && (
          <table className="w-full">
            <thead className="sticky top-0 z-10 bg-slate-950 text-[10px] uppercase tracking-wider text-slate-500">
              <tr>
                <th className="py-1 text-center text-emerald-500" colSpan={5}>
                  Calls
                </th>
                <th className="py-1 text-center">Strike</th>
                <th className="py-1 text-center text-red-500" colSpan={5}>
                  Puts
                </th>
              </tr>
              <tr className="text-right text-slate-500">
                <th className="px-1"></th>
                <th className="px-1">Bid</th>
                <th className="px-1">Ask</th>
                <th className="px-1">Last</th>
                <th className="px-1">Vol</th>
                <th className="px-1 text-center"></th>
                <th className="px-1">Last</th>
                <th className="px-1">Bid</th>
                <th className="px-1">Ask</th>
                <th className="px-1">Vol</th>
                <th className="px-1"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const atm = r.strike === atmStrike;
                return (
                  <tr key={r.strike} className={atm ? "bg-slate-800/50" : "hover:bg-slate-900/40"}>
                    <Side leg={r.call} side="call" flash={flash} onTrade={onTrade} />
                    <td className={`px-2 py-1 text-center font-bold ${atm ? "text-amber-400" : "text-white"}`}>
                      {num(r.strike)}
                    </td>
                    <Side leg={r.put} side="put" flash={flash} onTrade={onTrade} />
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function Side({
  leg,
  side,
  flash,
  onTrade,
}: {
  leg: ChainLeg | null;
  side: "call" | "put";
  flash: Record<string, "up" | "down">;
  onTrade: (contract: string, s: "BUY" | "SELL") => void;
}) {
  if (!leg) {
    return (
      <>
        {Array.from({ length: 5 }).map((_, i) => (
          <td key={i} className="px-1 py-1 text-right text-slate-700">
            —
          </td>
        ))}
      </>
    );
  }
  const dir = leg.contract ? flash[leg.contract] : undefined;
  const lastCls =
    dir === "up"
      ? "bg-emerald-500/25 text-emerald-300"
      : dir === "down"
        ? "bg-red-500/25 text-red-300"
        : leg.live
          ? "text-white"
          : "text-slate-400";
  const bs = (
    <span className="inline-flex gap-0.5">
      <button
        onClick={() => leg.contract && onTrade(leg.contract, "BUY")}
        className="broker-btn rounded bg-emerald-500/20 px-1 text-emerald-400 hover:bg-emerald-500 hover:text-slate-950"
      >
        B
      </button>
      <button
        onClick={() => leg.contract && onTrade(leg.contract, "SELL")}
        className="broker-btn rounded bg-red-500/20 px-1 text-red-400 hover:bg-red-500 hover:text-slate-950"
      >
        S
      </button>
    </span>
  );
  const cBid = (
    <td key="bid" className="px-1 py-1 text-right text-slate-400">
      {leg.bid != null ? num(leg.bid) : "—"}
    </td>
  );
  const cAsk = (
    <td key="ask" className="px-1 py-1 text-right text-slate-400">
      {leg.ask != null ? num(leg.ask) : "—"}
    </td>
  );
  const cLast = (
    <td key="last" className={`px-1 py-1 text-right transition-colors ${lastCls}`}>
      {leg.last != null ? num(leg.last) : "—"}
    </td>
  );
  const cVol = (
    <td key="vol" className="px-1 py-1 text-right text-slate-500">
      {leg.volume?.toLocaleString?.() ?? "—"}
    </td>
  );
  const trade = (
    <td key="bs" className="px-1 py-1 text-center">
      {bs}
    </td>
  );
  // Call: [BS] Bid Ask Last Vol  ·  Put: Last Bid Ask Vol [BS]
  return <>{side === "call" ? [trade, cBid, cAsk, cLast, cVol] : [cLast, cBid, cAsk, cVol, trade]}</>;
}
