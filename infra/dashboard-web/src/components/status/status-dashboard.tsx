"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { FreshnessTrendChart } from "@/components/charts/freshness-trend-chart";
import { ServiceCard } from "@/components/status/service-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { STATUS_REFRESH_MS } from "@/lib/config";
import { safeDate } from "@/lib/time";
import type { StatusSummaryResponse } from "@/lib/types";

async function fetchStatus(): Promise<StatusSummaryResponse> {
  const response = await fetch("/api/status", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to fetch status: ${response.status}`);
  }
  return response.json() as Promise<StatusSummaryResponse>;
}

export function StatusDashboard() {
  const status = useQuery({
    queryKey: ["status-summary"],
    queryFn: fetchStatus,
    refetchInterval: STATUS_REFRESH_MS,
  });

  const trendData = useMemo(() => {
    const now = Date.now();
    const cards = status.data?.cards ?? [];
    return cards.map((card) => {
      const latest = safeDate(card.latestDataAt);
      return {
        service: card.name,
        minutesBehind: latest ? Math.max(0, now - latest.getTime()) : 0,
      };
    });
  }, [status.data?.cards]);

  return (
    <div className="space-y-6">
      <Card className="overflow-hidden">
        <CardHeader className="border-b bg-muted/20">
          <CardTitle className="text-base font-medium">Service Lag Overview</CardTitle>
        </CardHeader>
        <CardContent className="pt-6">
          <FreshnessTrendChart data={trendData} />
        </CardContent>
      </Card>

      {status.isError ? (
        <Card border-destructive>
          <CardContent className="pt-6">
            <p className="text-sm text-destructive">{(status.error as Error).message}</p>
          </CardContent>
        </Card>
      ) : null}

      <div className="grid grid-cols-[repeat(auto-fit,minmax(320px,1fr))] gap-4">
        {(status.data?.cards ?? []).map((card) => (
          <ServiceCard key={card.name} card={card} />
        ))}
      </div>
    </div>
  );
}
