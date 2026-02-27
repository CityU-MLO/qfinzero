import { describe, expect, it } from "vitest";

import {
  computeServiceState,
  estimateFiveMinute,
  normalizeFreshnessTimestamp,
} from "@/lib/status";

describe("normalizeFreshnessTimestamp", () => {
  it("normalizes ISO string", () => {
    expect(normalizeFreshnessTimestamp("2026-02-19T10:00:00Z")?.toISOString()).toBe("2026-02-19T10:00:00.000Z");
  });

  it("normalizes nanosecond epoch number", () => {
    const ns = 1739966400000000000;
    expect(normalizeFreshnessTimestamp(ns)?.toISOString()).toBe("2025-02-19T12:00:00.000Z");
  });
});

describe("estimateFiveMinute", () => {
  it("estimates request and error volume from stats", () => {
    const estimate = estimateFiveMinute({
      total_requests: 1000,
      total_errors: 20,
      endpoints: {
        "GET /a": { last_60s: { count: 12, avg_ms: 10, rpm: 12 } },
        "GET /b": { last_60s: { count: 18, avg_ms: 15, rpm: 18 } },
      },
    } as any);

    expect(estimate.requests).toBe(150);
    expect(estimate.errors).toBe(3);
  });
});

describe("computeServiceState", () => {
  it("returns down when service is unreachable", () => {
    expect(computeServiceState({
      isUp: false,
      freshestAt: null,
      sourceName: "news",
      now: new Date("2026-02-19T12:00:00Z"),
    })).toBe("down");
  });

  it("returns stale when freshness is older than threshold", () => {
    expect(computeServiceState({
      isUp: true,
      freshestAt: new Date("2026-02-19T01:00:00Z"),
      sourceName: "news",
      now: new Date("2026-02-19T12:00:00Z"),
    })).toBe("stale");
  });

  it("returns running when freshness is fresh", () => {
    expect(computeServiceState({
      isUp: true,
      freshestAt: new Date("2026-02-19T11:50:00Z"),
      sourceName: "stock_minute",
      now: new Date("2026-02-19T12:00:00Z"),
    })).toBe("running");
  });
});
