"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";

import { NewsDetailDrawer } from "@/components/news/news-detail-drawer";
import { NewsSearchPanel } from "@/components/news/news-search-panel";
import { NewsStatsCharts } from "@/components/news/news-stats-charts";
import { NewsTable } from "@/components/news/news-table";
import { Button } from "@/components/ui/button";
import type { NewsBodyResponse, NewsStatsResponse, NppEvent, PaginatedEventsResponse } from "@/lib/types";

type NewsFilters = {
  tickers: string;
  startUtc: string;
  endUtc: string;
  keyword: string;
  publisher: string;
  limit: number;
};

const DEFAULT_FILTERS: NewsFilters = {
  tickers: "",
  startUtc: "",
  endUtc: "",
  keyword: "",
  publisher: "",
  limit: 50,
};

function parseTickers(value: string): string[] | undefined {
  const list = value
    .split(",")
    .map((v) => v.trim().toUpperCase())
    .filter(Boolean);
  return list.length > 0 ? list : undefined;
}

function toIso(value: string): string | undefined {
  if (!value) {
    return undefined;
  }
  return new Date(value).toISOString();
}

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

export function NewsBrowser() {
  const [filters, setFilters] = React.useState<NewsFilters>(DEFAULT_FILTERS);
  const [result, setResult] = React.useState<PaginatedEventsResponse | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [selected, setSelected] = React.useState<NppEvent | null>(null);

  const stats = useQuery({
    queryKey: ["news-stats", 7],
    queryFn: () => getJson<NewsStatsResponse>("/api/npp/news/stats?days=7"),
  });

  const bodyQuery = useQuery({
    queryKey: ["news-body", selected?.source_id],
    enabled: Boolean(selected?.source_id),
    queryFn: () => getJson<NewsBodyResponse>(`/api/npp/news/body/${encodeURIComponent(selected?.source_id ?? "")}`),
  });

  const runSearch = React.useCallback(
    async (cursor?: string) => {
      setLoading(true);
      setError(null);

      try {
        const payload = {
          tickers: parseTickers(filters.tickers),
          start_utc: toIso(filters.startUtc),
          end_utc: toIso(filters.endUtc),
          keyword: filters.keyword || undefined,
          publisher: filters.publisher || undefined,
          limit: filters.limit,
          cursor,
        };

        const data = await postJson<PaginatedEventsResponse>("/api/npp/news/search", payload);
        setResult(data);
        if (!cursor) {
          setSelected(data.events[0] ?? null);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "news search failed");
      } finally {
        setLoading(false);
      }
    },
    [filters],
  );

  React.useEffect(() => {
    void runSearch();
  }, [runSearch]);

  const exportQuery = React.useMemo(() => {
    const qs = new URLSearchParams();
    if (filters.tickers.trim()) {
      qs.set("tickers", filters.tickers.trim());
    }
    if (filters.startUtc) {
      qs.set("start", toIso(filters.startUtc) ?? "");
    }
    if (filters.endUtc) {
      qs.set("end", toIso(filters.endUtc) ?? "");
    }
    return qs.toString();
  }, [filters.endUtc, filters.startUtc, filters.tickers]);

  const applyPreset = React.useCallback((preset: "aapl_window" | "nvda_last_day" | "macro_earnings") => {
    const now = new Date();
    if (preset === "aapl_window") {
      setFilters({
        tickers: "AAPL",
        startUtc: "2025-01-01T00:00",
        endUtc: "2025-01-03T23:59",
        keyword: "",
        publisher: "",
        limit: 50,
      });
      return;
    }

    if (preset === "nvda_last_day") {
      const dayAgo = new Date(now.getTime() - 24 * 60 * 60 * 1000);
      setFilters({
        tickers: "NVDA",
        startUtc: dayAgo.toISOString().slice(0, 16),
        endUtc: now.toISOString().slice(0, 16),
        keyword: "",
        publisher: "",
        limit: 50,
      });
      return;
    }

    setFilters({
      tickers: "",
      startUtc: "",
      endUtc: "",
      keyword: "earnings",
      publisher: "",
      limit: 50,
    });
  }, []);

  React.useEffect(() => {
    if (!selected && result?.events?.length) {
      setSelected(result.events[0]);
    }
  }, [result, selected]);

  return (
    <div className="space-y-4">
      <NewsSearchPanel
        filters={filters}
        onChange={setFilters}
        onSearch={() => void runSearch()}
        onPreset={applyPreset}
        isLoading={loading}
      />

      <div className="flex flex-wrap gap-2">
        <Button asChild variant="outline">
          <a href={`/api/npp/news/export?format=jsonl${exportQuery ? `&${exportQuery}` : ""}`} target="_blank" rel="noreferrer">
            Export JSONL
          </a>
        </Button>
        <Button asChild variant="outline">
          <a href={`/api/npp/news/export?format=csv${exportQuery ? `&${exportQuery}` : ""}`} target="_blank" rel="noreferrer">
            Export CSV
          </a>
        </Button>
      </div>

      {error ? <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p> : null}

      <NewsStatsCharts stats={stats.data ?? null} />

      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <div className="space-y-3">
          <NewsTable rows={result?.events ?? []} selectedId={selected?.event_id ?? null} onSelect={setSelected} />

          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              Returned {result?.events.length ?? 0} rows
            </p>
            <Button
              variant="secondary"
              disabled={!result?.next_cursor || loading}
              onClick={() => void runSearch(result?.next_cursor ?? undefined)}
            >
              Next Page
            </Button>
          </div>
        </div>

        <NewsDetailDrawer 
          selected={selected} 
          article={bodyQuery.data ?? null} 
          onClose={() => setSelected(null)}
        />
      </div>
    </div>
  );
}
