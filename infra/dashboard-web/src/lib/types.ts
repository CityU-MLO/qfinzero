export type HealthStatus = "running" | "down" | "stale";

export type ServiceName = "UPQ" | "NPP" | "PMB";

export type ServiceHealthPayload = {
  status?: string;
  service?: string;
  version?: string;
  data_freshness?: Record<string, unknown>;
};

export type EndpointStats = {
  count: number;
  errors: number;
  latency_ms: {
    p50: number;
    p95: number;
    p99: number;
    avg: number;
    max: number;
  };
  last_60s: {
    count: number;
    avg_ms: number;
    rpm: number;
  };
};

export type ServiceStatsPayload = {
  service?: string;
  uptime_seconds: number;
  total_requests: number;
  total_errors: number;
  active_requests: number;
  endpoints: Record<string, EndpointStats>;
};

export type FreshnessSource = {
  latest_timestamp?: string | number | null;
  latest_date?: string | null;
  record_count?: number;
  unique_keys?: number;
  unique_key_label?: string;
  partition_count?: number;
  metadata?: Record<string, unknown>;
  missing_dates?: string[];
};

export type FreshnessPayload = {
  service: string;
  checked_at: string;
  sources: Record<string, FreshnessSource>;
};

export type FiveMinuteEstimate = {
  requests: number | null;
  errors: number | null;
};

export type ServiceStatusCard = {
  name: ServiceName;
  baseUrl: string;
  port: string | null;
  healthPath: string;
  state: HealthStatus;
  version: string | null;
  uptimeSeconds: number | null;
  activeRequests: number | null;
  requests5m: number | null;
  errors5m: number | null;
  health: ServiceHealthPayload | null;
  stats: ServiceStatsPayload | null;
  freshness: FreshnessPayload | null;
  latestDataAt: string | null;
  staleReason: string | null;
};

export type StatusSummaryResponse = {
  checkedAt: string;
  cards: ServiceStatusCard[];
};

export type NppEvent = {
  event_id: string;
  event_type: "macro_calendar" | "earnings" | "breaking_news" | "daily_news";
  title: string;
  time_utc: string;
  importance: "low" | "medium" | "high";
  status: "scheduled" | "occurred" | "updated";
  tickers: string[];
  country: string;
  snippet: string;
  payload: Record<string, unknown>;
  source: string;
  source_id: string;
};

export type PaginatedEventsResponse = {
  server_time_utc: string;
  events: NppEvent[];
  next_cursor: string | null;
};

export type NewsBodyResponse = {
  news_id: string;
  title: string;
  description?: string;
  article_url?: string;
  published_utc?: string;
  tickers: string[];
  author?: string;
  keywords: string[];
  image_url?: string;
  publisher?: Record<string, unknown>;
  insights?: Record<string, unknown>;
};

export type NewsStatsResponse = {
  total_count: number;
  date_range: { earliest: string | null; latest: string | null };
  daily_counts: Array<{ date: string; count: number }>;
  top_tickers: Array<{ ticker: string; count: number }>;
  top_publishers: Array<{ publisher: string; count: number }>;
  duplicate_stats: {
    by_url: { total: number; unique: number; duplicate_rate: number };
    by_title: { total: number; unique: number; duplicate_rate: number };
  };
};

export type CoverageResponse = {
  earnings: {
    date_range: { start: string | null; end: string | null };
    total_records: number;
    daily_counts: Array<{ date: string; count: number }>;
    missing_dates: string[];
    by_importance: Record<string, number>;
  };
  econ_events: {
    date_range: { start: string | null; end: string | null };
    total_records: number;
    daily_counts: Array<{ date: string; count: number }>;
    missing_dates: string[];
    by_country: Record<string, number>;
    by_type_top10: Array<{ event_type: string; count: number }>;
  };
};

export type SanityResponse = {
  checked_at: string;
  summary: {
    total: number;
    pass: number;
    warn: number;
    fail: number;
  };
  checks: Array<{
    name: string;
    description: string;
    status: "pass" | "warn" | "fail";
    count: number;
    samples: Record<string, unknown>[];
  }>;
};
