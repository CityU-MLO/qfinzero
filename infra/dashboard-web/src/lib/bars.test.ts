import { describe, expect, it } from "vitest";

import { aggregate, chartTime, etOffsetSec, fromDailyRows, mergeBars, sma, vwap, type Bar } from "./bars";
import { kindOf } from "./qfzview";

const MIN = 60e9;
// 2026-08-21 13:30 UTC = 09:30 EDT
const OPEN = Date.UTC(2026, 7, 21, 13, 30) * 1e6;
const bar = (i: number, close: number, volume = 100): Bar =>
  ({ ns: OPEN + i * MIN, day: "2026-08-21", open: close, high: close + 1, low: close - 1, close, volume });

describe("bars", () => {
  it("shows US bars in Eastern time and pairs in UTC", () => {
    expect(etOffsetSec(OPEN / 1e6)).toBe(-4 * 3600);                              // summer
    expect(etOffsetSec(Date.UTC(2026, 0, 5, 15) )).toBe(-5 * 3600);              // winter
    expect(new Date(chartTime(OPEN, "et") * 1000).toISOString().slice(11, 16)).toBe("09:30");
    expect(new Date(chartTime(OPEN, "utc") * 1000).toISOString().slice(11, 16)).toBe("13:30");
  });

  it("aggregates minutes on the wall clock", () => {
    const five = aggregate([0, 1, 2, 3, 4, 5].map((i) => bar(i, 100 + i)), 5, "et");
    expect(five).toHaveLength(2);
    expect(five[0]).toMatchObject({ ns: OPEN, open: 100, close: 104, high: 105, low: 99, volume: 500 });
    expect(five[1].ns).toBe(OPEN + 5 * MIN);
  });

  it("merges pages and computes indicators", () => {
    const a = [bar(0, 1), bar(1, 2)];
    const b = [bar(1, 20), bar(2, 3)];
    expect(mergeBars(a, b).map((x) => x.close)).toEqual([1, 20, 3]);
    expect(sma([bar(0, 1), bar(1, 2), bar(2, 3)], 2, (x) => x.ns).map((p) => p.value)).toEqual([1.5, 2.5]);
    expect(vwap([bar(0, 10, 1), bar(1, 20, 3)], (x) => x.ns)[1].value).toBeCloseTo(17.5);
    expect(fromDailyRows([{ date: "2026-02-24", close: 64061.9, volume: 20134.07 }])[0].volume).toBeCloseTo(20134.07);
  });

  it("knows the kind of a symbol", () => {
    expect(kindOf("/cl")).toEqual({ kind: "future", name: "CL" });
    expect(kindOf("X:BTC-USD").kind).toBe("crypto");
    expect(kindOf("C:EUR-USD").name).toBe("EUR-USD");
    expect(kindOf("O:SPY260821C00766000").kind).toBe("option");
    expect(kindOf("spy")).toEqual({ kind: "stock", name: "SPY" });
  });
});
