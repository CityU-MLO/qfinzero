import { safeDate } from "@/lib/time";
import type { FreshnessPayload, FiveMinuteEstimate, ServiceStatsPayload } from "@/lib/types";

export function normalizeFreshnessTimestamp(value: unknown): Date | null {
  if (value == null) {
    return null;
  }

  if (typeof value === "number") {
    return safeDate(value);
  }

  if (typeof value === "string") {
    return safeDate(value);
  }

  return null;
}

function staleThresholdMs(sourceName: string): number {
  const name = sourceName.toLowerCase();
  if (name.includes("minute")) {
    return 20 * 60 * 1000;
  }
  if (name.includes("news")) {
    return 6 * 60 * 60 * 1000;
  }
  if (name.includes("daily") || name.includes("rates") || name.includes("earn") || name.includes("econ")) {
    return 36 * 60 * 60 * 1000;
  }
  return 24 * 60 * 60 * 1000;
}

export function computeServiceState(params: {
  isUp: boolean;
  freshestAt: Date | null;
  sourceName: string;
  now?: Date;
}): "running" | "stale" | "down" {
  if (!params.isUp) {
    return "down";
  }
  if (!params.freshestAt) {
    return "running";
  }

  const now = params.now ?? new Date();
  const diff = now.getTime() - params.freshestAt.getTime();
  if (diff > staleThresholdMs(params.sourceName)) {
    return "stale";
  }
  return "running";
}

export function getFreshestPoint(freshness: FreshnessPayload | null): {
  sourceName: string;
  timestamp: Date | null;
  isoValue: string | null;
} {
  if (!freshness?.sources) {
    return { sourceName: "", timestamp: null, isoValue: null };
  }

  let best: { sourceName: string; timestamp: Date | null; isoValue: string | null } = {
    sourceName: "",
    timestamp: null,
    isoValue: null,
  };

  for (const [sourceName, source] of Object.entries(freshness.sources)) {
    const raw = source.latest_timestamp ?? source.latest_date ?? null;
    const parsed = normalizeFreshnessTimestamp(raw);
    if (!parsed) {
      continue;
    }

    if (!best.timestamp || parsed.getTime() > best.timestamp.getTime()) {
      best = {
        sourceName,
        timestamp: parsed,
        isoValue: parsed.toISOString(),
      };
    }
  }

  return best;
}

export function estimateFiveMinute(stats: Pick<ServiceStatsPayload, "total_requests" | "total_errors" | "endpoints">): FiveMinuteEstimate {
  if (!stats?.endpoints) {
    return { requests: null, errors: null };
  }

  let lastMinute = 0;
  for (const endpoint of Object.values(stats.endpoints)) {
    lastMinute += endpoint?.last_60s?.count ?? 0;
  }

  const requests = lastMinute * 5;
  if (requests <= 0 || stats.total_requests <= 0) {
    return { requests, errors: 0 };
  }

  const errorRate = stats.total_errors / stats.total_requests;
  const errors = Math.round(requests * errorRate);
  return { requests, errors };
}
