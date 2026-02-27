"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";

import { CalendarFiltersPanel } from "@/components/calendar/calendar-filters";
import { CalendarTable } from "@/components/calendar/calendar-table";
import { CoverageHeatmap } from "@/components/calendar/coverage-heatmap";
import { JsonViewer } from "@/components/news/json-viewer";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { CoverageResponse, NppEvent, PaginatedEventsResponse } from "@/lib/types";

async function postJson<T>(url: string, payload: Record<string, unknown>): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json() as Promise<T>;
}

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json() as Promise<T>;
}

type CalendarFilters = {
  startDate: string;
  endDate: string;
  tickers: string;
  country: string;
  minImportance: string;
  limit: number;
};

const defaultFilters: CalendarFilters = {
  startDate: "",
  endDate: "",
  tickers: "",
  country: "United States",
  minImportance: "",
  limit: 100,
};

function splitTickers(input: string): string[] | undefined {
  const out = input
    .split(",")
    .map((token) => token.trim().toUpperCase())
    .filter(Boolean);
  return out.length ? out : undefined;
}

export function CalendarBrowser() {
  const [mode, setMode] = React.useState<"earnings" | "econ">("earnings");
  const [filters, setFilters] = React.useState<CalendarFilters>(defaultFilters);
  const [rows, setRows] = React.useState<NppEvent[]>([]);
  const [cursor, setCursor] = React.useState<string | null>(null);
  const [prevCursor, setPrevCursor] = React.useState<string | null>(null);
  const [selected, setSelected] = React.useState<NppEvent | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const coverage = useQuery({
    queryKey: ["calendar-coverage", 60],
    queryFn: () => getJson<CoverageResponse>("/api/npp/calendar/coverage?days=60"),
  });

  const runQuery = React.useCallback(
    async (nextCursor?: string, isPrevious?: boolean) => {
      setLoading(true);
      setError(null);

      try {
        const payload =
          mode === "earnings"
            ? {
                start_date: filters.startDate || undefined,
                end_date: filters.endDate || undefined,
                tickers: splitTickers(filters.tickers),
                min_importance: filters.minImportance ? Number(filters.minImportance) || 0 : 0,
                limit: filters.limit,
                cursor: nextCursor,
              }
            : {
                start_date: filters.startDate || undefined,
                end_date: filters.endDate || undefined,
                min_importance: filters.minImportance || undefined,
                limit: filters.limit,
                cursor: nextCursor,
              };

        const endpoint = mode === "earnings" ? "/api/npp/calendar/earnings" : "/api/npp/calendar/econ";
        const data = await postJson<PaginatedEventsResponse>(endpoint, payload);

        setRows(data.events);
        if (isPrevious) {
          setPrevCursor(null);
        } else {
          setPrevCursor(cursor);
        }
        setCursor(data.next_cursor);
        setSelected(data.events[0] ?? null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "calendar query failed");
      } finally {
        setLoading(false);
      }
    },
    [filters, mode, cursor],
  );

  React.useEffect(() => {
    void runQuery();
  }, [runQuery]);

  const exportQuery = React.useMemo(() => {
    const qs = new URLSearchParams();
    if (filters.startDate) {
      qs.set("start", filters.startDate);
    }
    if (filters.endDate) {
      qs.set("end", filters.endDate);
    }
    if (mode === "earnings") {
      if (filters.tickers.trim()) {
        qs.set("ticker", filters.tickers.trim());
      }
      return `/api/npp/calendar/earnings/export?format=csv${qs.toString() ? `&${qs.toString()}` : ""}`;
    }

    qs.set("country", filters.country || "United States");
    return `/api/npp/calendar/economic/export?format=csv${qs.toString() ? `&${qs.toString()}` : ""}`;
  }, [filters.country, filters.endDate, filters.startDate, filters.tickers, mode]);

  return (
    <div className="space-y-4">
      <CalendarFiltersPanel
        mode={mode}
        onMode={setMode}
        filters={filters}
        onChange={setFilters}
        onQuery={() => void runQuery()}
        loading={loading}
        exportQuery={exportQuery}
      />

      {error ? <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p> : null}

      <div className="grid gap-4 xl:grid-cols-[2fr_1fr]">
        <div className="space-y-3">
          <CalendarTable rows={rows} selectedId={selected?.event_id ?? null} onSelect={setSelected} />
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">Rows: {rows.length}</p>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                disabled={!prevCursor || loading}
                onClick={() => void runQuery(prevCursor ?? undefined, true)}
              >
                Previous
              </Button>
              <Button variant="secondary" disabled={!cursor || loading} onClick={() => void runQuery(cursor ?? undefined)}>
                Next Page
              </Button>
            </div>
          </div>
        </div>

        <Card>
          <CardHeader className="relative pb-2">
            <CardTitle className="text-base">Row Details</CardTitle>
            {selected && (
              <Button
                variant="ghost"
                size="icon"
                className="absolute right-2 top-2 h-7 w-7"
                onClick={() => setSelected(null)}
              >
                <X className="h-4 w-4" />
              </Button>
            )}
          </CardHeader>
          <CardContent>
            {selected ? (
              <JsonViewer data={selected} title="Event Details" />
            ) : (
              <p className="text-sm text-muted-foreground">Select a row to view details</p>
            )}
          </CardContent>
        </Card>
      </div>

      {coverage.data ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <CoverageHeatmap
            title="Earnings Coverage Heatmap"
            dailyCounts={coverage.data.earnings.daily_counts}
            start={coverage.data.earnings.date_range.start}
            end={coverage.data.earnings.date_range.end}
          />
          <CoverageHeatmap
            title="Economic Coverage Heatmap"
            dailyCounts={coverage.data.econ_events.daily_counts}
            start={coverage.data.econ_events.date_range.start}
            end={coverage.data.econ_events.date_range.end}
          />
        </div>
      ) : null}
    </div>
  );
}
