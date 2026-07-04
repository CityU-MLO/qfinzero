"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";

import { optionChain, num, type OptionRow } from "./api";

export function OptionChain({
  underlying,
  date,
  spot,
  onTrade,
}: {
  underlying: string;
  date: string;
  spot?: number;
  onTrade: (row: OptionRow, side: "BUY" | "SELL") => void;
}) {
  const [rows, setRows] = useState<OptionRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [type, setType] = useState<"C" | "P">("C");
  const [expiry, setExpiry] = useState<string>("");

  useEffect(() => {
    if (!underlying || !date) return;
    let cancelled = false;
    setLoading(true);
    setErr(null);
    optionChain(underlying, date)
      .then((r) => {
        if (cancelled) return;
        setRows(r);
        const exps = Array.from(new Set(r.map((x) => x.expiry))).sort();
        setExpiry((cur) => (cur && exps.includes(cur) ? cur : exps[0] ?? ""));
      })
      .catch((e) => !cancelled && setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [underlying, date]);

  const expiries = useMemo(
    () => Array.from(new Set(rows.map((r) => r.expiry))).sort(),
    [rows],
  );

  const shown = useMemo(
    () =>
      rows
        .filter((r) => r.type === type && r.expiry === expiry)
        .sort((a, b) => a.strike - b.strike),
    [rows, type, expiry],
  );

  const atmStrike = useMemo(() => {
    if (!spot || !shown.length) return null;
    return shown.reduce((best, r) =>
      Math.abs(r.strike - spot) < Math.abs(best.strike - spot) ? r : best,
    ).strike;
  }, [shown, spot]);

  return (
    <div className="broker-panel flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-3 border-b border-slate-800 px-4 py-2">
        <div className="text-sm font-bold text-white">
          {underlying} <span className="text-slate-500">options</span>
        </div>
        <div className="flex overflow-hidden rounded-lg border border-slate-700">
          {(["C", "P"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setType(t)}
              className={`px-3 py-1 text-xs font-semibold ${
                type === t
                  ? t === "C"
                    ? "bg-emerald-500 text-slate-950"
                    : "bg-red-500 text-slate-950"
                  : "bg-slate-900 text-slate-400"
              }`}
            >
              {t === "C" ? "Calls" : "Puts"}
            </button>
          ))}
        </div>
        <select
          value={expiry}
          onChange={(e) => setExpiry(e.target.value)}
          className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-white"
        >
          {expiries.map((x) => (
            <option key={x} value={x}>
              exp {x}
            </option>
          ))}
        </select>
        {spot && <span className="text-xs text-slate-500">spot {num(spot)}</span>}
        {loading && <Loader2 className="h-4 w-4 animate-spin text-slate-400" />}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-1 font-mono text-xs">
        {err && <div className="p-4 text-red-400">{err}</div>}
        {!err && !loading && !shown.length && (
          <div className="p-6 text-center text-slate-600">No contracts for this expiry.</div>
        )}
        {!!shown.length && (
          <table className="w-full">
            <thead className="sticky top-0 bg-slate-950 text-slate-500">
              <tr className="text-right">
                <th className="py-1 text-left">Strike</th>
                <th>Last</th>
                <th>IV</th>
                <th>Δ</th>
                <th>Vol</th>
                <th className="text-center">Trade</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => {
                const atm = r.strike === atmStrike;
                return (
                  <tr
                    key={r.ticker}
                    className={`text-right ${atm ? "bg-slate-800/60" : "hover:bg-slate-900/60"}`}
                  >
                    <td className={`py-1 text-left font-semibold ${atm ? "text-amber-400" : "text-white"}`}>
                      {num(r.strike)}
                    </td>
                    <td>{num(r.close)}</td>
                    <td className="text-slate-400">{r.iv != null ? `${(r.iv * 100).toFixed(1)}%` : "—"}</td>
                    <td className="text-slate-400">{r.delta != null ? num(r.delta, 2) : "—"}</td>
                    <td className="text-slate-500">{r.volume?.toLocaleString?.() ?? r.volume}</td>
                    <td className="text-center">
                      <span className="inline-flex gap-1">
                        <button
                          onClick={() => onTrade(r, "BUY")}
                          className="rounded bg-emerald-500/20 px-1.5 py-0.5 text-emerald-400 hover:bg-emerald-500 hover:text-slate-950"
                        >
                          B
                        </button>
                        <button
                          onClick={() => onTrade(r, "SELL")}
                          className="rounded bg-red-500/20 px-1.5 py-0.5 text-red-400 hover:bg-red-500 hover:text-slate-950"
                        >
                          S
                        </button>
                      </span>
                    </td>
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
