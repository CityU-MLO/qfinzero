import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ServiceCard } from "@/components/status/service-card";
import type { ServiceStatusCard } from "@/lib/types";

const sample: ServiceStatusCard = {
  name: "ESP",
  baseUrl: "http://127.0.0.1:19702",
  port: "19702",
  healthPath: "/esp/health",
  state: "stale",
  version: "qfinzero:deadbee",
  uptimeSeconds: 100,
  activeRequests: 1,
  requests5m: 25,
  errors5m: 1,
  health: { status: "ok" },
  stats: null,
  freshness: {
    service: "esp",
    checked_at: "2026-02-19T00:00:00Z",
    sources: {
      news: {
        latest_timestamp: "2026-02-18T00:00:00Z",
        record_count: 10,
        unique_keys: 2,
        unique_key_label: "tickers",
      },
    },
  },
  latestDataAt: "2026-02-18T00:00:00Z",
  staleReason: "news is older than threshold",
};

describe("ServiceCard", () => {
  it("shows stale badge", () => {
    render(<ServiceCard card={sample} />);
    expect(screen.getByText("Stale")).toBeInTheDocument();
    expect(screen.getByText("news is older than threshold")).toBeInTheDocument();
  });
});
