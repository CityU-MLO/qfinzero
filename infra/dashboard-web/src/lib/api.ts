import { NPP_BASE_URL, NPP_API_TOKEN, SERVICES, extractPort } from "@/lib/config";
import { computeServiceState, estimateFiveMinute, getFreshestPoint } from "@/lib/status";
import type {
  CoverageResponse,
  FreshnessPayload,
  NewsBodyResponse,
  NewsStatsResponse,
  PaginatedEventsResponse,
  SanityResponse,
  ServiceHealthPayload,
  ServiceStatusCard,
  ServiceStatsPayload,
  StatusSummaryResponse,
} from "@/lib/types";

const DEFAULT_TIMEOUT_MS = 5_000;

type FetchOptions = RequestInit & { timeoutMs?: number };

function addTokenToUrl(url: string, token?: string): string {
  if (!token) return url;
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}apifoxToken=${encodeURIComponent(token)}`;
}

async function fetchJson<T>(url: string, options?: FetchOptions, token?: string): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options?.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  const urlWithToken = addTokenToUrl(url, token);

  try {
    const response = await fetch(urlWithToken, {
      ...options,
      cache: "no-store",
      signal: controller.signal,
      headers: {
        "content-type": "application/json",
        ...(options?.headers ?? {}),
      },
    });

    if (!response.ok) {
      throw new Error(`${response.status} ${response.statusText}`);
    }

    return (await response.json()) as T;
  } finally {
    clearTimeout(timeout);
  }
}

async function maybeFetchJson<T>(url: string, token?: string): Promise<T | null> {
  try {
    return await fetchJson<T>(url, undefined, token);
  } catch {
    return null;
  }
}

export async function getStatusSummary(): Promise<StatusSummaryResponse> {
  const cards = await Promise.all(
    SERVICES.map(async (svc): Promise<ServiceStatusCard> => {
      const [health, stats, freshness] = await Promise.all([
        maybeFetchJson<ServiceHealthPayload>(`${svc.baseUrl}${svc.healthPath}`, svc.apiToken),
        svc.statsPath ? maybeFetchJson<ServiceStatsPayload>(`${svc.baseUrl}${svc.statsPath}`, svc.apiToken) : Promise.resolve(null),
        svc.freshnessPath ? maybeFetchJson<FreshnessPayload>(`${svc.baseUrl}${svc.freshnessPath}`, svc.apiToken) : Promise.resolve(null),
      ]);

      const isUp = health?.status === "ok" || Boolean(stats);
      const freshest = getFreshestPoint(freshness);
      const state = computeServiceState({
        isUp,
        freshestAt: freshest.timestamp,
        sourceName: freshest.sourceName,
      });
      const fiveMinute = stats ? estimateFiveMinute(stats) : { requests: null, errors: null };

      return {
        name: svc.name,
        baseUrl: svc.baseUrl,
        port: extractPort(svc.baseUrl),
        healthPath: svc.healthPath,
        state,
        version: health?.version ?? null,
        uptimeSeconds: stats?.uptime_seconds ?? null,
        activeRequests: stats?.active_requests ?? null,
        requests5m: fiveMinute.requests,
        errors5m: fiveMinute.errors,
        health,
        stats,
        freshness,
        latestDataAt: freshest.isoValue,
        staleReason: state === "stale" ? `${freshest.sourceName || "source"} is older than threshold` : null,
      };
    }),
  );

  return {
    checkedAt: new Date().toISOString(),
    cards,
  };
}

export async function nppSearchNews(payload: Record<string, unknown>): Promise<PaginatedEventsResponse> {
  return fetchJson<PaginatedEventsResponse>(`${NPP_BASE_URL}/npp/news/search`, {
    method: "POST",
    body: JSON.stringify(payload),
  }, NPP_API_TOKEN);
}

export async function nppNewsStats(days: number): Promise<NewsStatsResponse> {
  return fetchJson<NewsStatsResponse>(`${NPP_BASE_URL}/npp/news/stats?days=${days}`, undefined, NPP_API_TOKEN);
}

export async function nppNewsBody(newsId: string): Promise<NewsBodyResponse> {
  return fetchJson<NewsBodyResponse>(`${NPP_BASE_URL}/npp/news/${encodeURIComponent(newsId)}/body`, undefined, NPP_API_TOKEN);
}

export async function nppCalendarEarnings(payload: Record<string, unknown>): Promise<PaginatedEventsResponse> {
  return fetchJson<PaginatedEventsResponse>(`${NPP_BASE_URL}/npp/calendar/earnings`, {
    method: "POST",
    body: JSON.stringify(payload),
  }, NPP_API_TOKEN);
}

export async function nppCalendarEconomic(payload: Record<string, unknown>): Promise<PaginatedEventsResponse> {
  return fetchJson<PaginatedEventsResponse>(`${NPP_BASE_URL}/npp/calendar/econ`, {
    method: "POST",
    body: JSON.stringify(payload),
  }, NPP_API_TOKEN);
}

export async function nppCoverage(days: number): Promise<CoverageResponse> {
  return fetchJson<CoverageResponse>(`${NPP_BASE_URL}/npp/calendar/coverage?days=${days}`, undefined, NPP_API_TOKEN);
}

export async function nppSanity(): Promise<SanityResponse> {
  return fetchJson<SanityResponse>(`${NPP_BASE_URL}/npp/admin/sanity`, undefined, NPP_API_TOKEN);
}

export async function proxyExport(path: string, request: Request): Promise<Response> {
  const target = addTokenToUrl(`${NPP_BASE_URL}${path}`, NPP_API_TOKEN);
  const upstream = await fetch(target, {
    method: "GET",
    cache: "no-store",
    headers: {
      accept: request.headers.get("accept") ?? "*/*",
    },
  });

  if (!upstream.ok || !upstream.body) {
    const message = await upstream.text();
    return new Response(message || `Export failed: ${upstream.status}`, {
      status: upstream.status,
      headers: { "content-type": "text/plain" },
    });
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "application/octet-stream",
      "content-disposition": upstream.headers.get("content-disposition") ?? "attachment",
    },
  });
}
