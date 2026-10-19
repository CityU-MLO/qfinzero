// Typed client for the data-admin service (via the /api/data-admin proxy).

const BASE = "/api/data-admin";

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}/${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok) throw new Error((data && (data.error || (typeof data.detail === "string" ? data.detail : ""))) || `HTTP ${res.status}`);
  return data as T;
}

export type SetupStep = { id: string; label: string; done: boolean; required: boolean; detail: string };
export type SetupState = {
  configured: boolean;
  initialized: boolean;
  show_wizard: boolean;
  has_credentials: boolean;
  steps: SetupStep[];
};

export type Config = {
  dirs: Record<string, string>;
  massive: Record<string, string>;
  tushare: Record<string, string>;
  databento?: Record<string, string>;
  news: Record<string, string>;
  schedule: Record<string, { enabled: boolean; cron: string; command?: string }>;
};

export type Source = {
  id: string;
  domain: string;
  market: string | null;
  owner: string;
  raw_max: string | null;
  store_max: string | null;
  state: string;
  colour: "green" | "amber" | "red" | "grey";
  will_run?: boolean;
  last_run?: { status?: string; last_run_ts?: string; rows?: number } | null;
};

export type JobProgress = {
  stage?: string;
  current?: string;
  files_total?: number;
  files_done?: number;
  files_failed?: number;
  bytes_total?: number;
  bytes_done?: number;
  billable_bytes?: number;
  rate_bps?: number;
  eta_s?: number;
  elapsed_s?: number;
  cost_usd?: number;
};

export type Job = {
  id: string;
  kind: string;
  label: string;
  status: "queued" | "running" | "done" | "error" | "cancelled" | "interrupted";
  error?: string | null;
  created_at?: string;
  started_at?: string | null;
  ended_at?: string | null;
  n_lines?: number;
  lines?: string[];
  result?: unknown;
  progress?: JobProgress;
  meta?: { vendor?: string; product?: string; key_id?: string; key_label?: string; max_cost?: number };
  cancel_requested?: boolean;
};

export type VendorKey = {
  id: string;
  label?: string;
  products: string[];
  note?: string;
  monthly_budget_usd?: number | null;
  s3_endpoint?: string;
  // masked secrets (••••last4) or ""
  api_key?: string;
  s3_access_key_id?: string;
  s3_secret_access_key?: string;
  rest_api_key?: string;
};

export type Spend = {
  month: string;
  by_key: Record<string, number>;
  budgets: Record<string, number>;
  total: number;
  recent: { ts: string; key_id: string; dataset: string; schema: string; cost_usd: number; files: number; job: string }[];
};

export type KeysView = {
  keys: Record<Vendor, VendorKey[]>;
  catalog: Record<Vendor, { product: string; name: string }[]>;
  spend: Spend;
};

export type DirInfo = {
  path: string;
  exists: boolean;
  writable: boolean;
  free_bytes: number | null;
  total_bytes: number | null;
  marker: { kind: string; vendor?: string; layout_version?: number; created_at?: string } | null;
  config_key: string;
  holds: string;
};

export type Layout = {
  raw: Record<"massive" | "databento" | "tushare", DirInfo>;
  qfz: DirInfo & { stores?: Record<string, boolean>; format: { compression: string; level: number; row_group_rows: number } };
  data_root: string;
  config_file: string;
};

export type ScanResult = {
  provider: string;
  ok: boolean;
  s3?: { ok: boolean; error?: string; datasets?: { name: string; required: boolean; label: string }[]; missing_required?: string[] };
  rest?: { ok: boolean; error?: string; status?: string };
  tushare?: { ok: boolean; error?: string; rows?: number };
  databento?: { ok: boolean; error?: string; count?: number; datasets?: { name: string; label: string; converted: boolean }[] };
};

export const dataAdmin = {
  setupState: () => j<SetupState>("data/setup-state"),
  getConfig: () => j<Config>("data/config"),
  putConfig: (patch: Partial<Config>) => j<Config>("data/config", { method: "PUT", body: JSON.stringify(patch) }),
  scan: (provider: string) => j<ScanResult>("data/scan", { method: "POST", body: JSON.stringify({ provider }) }),
  sources: () => j<{ sources: Source[] }>("data/status"),
  startUpdate: (body: { source?: string; market?: string | null; dry_run?: boolean; force?: boolean }) =>
    j<Job>("data/update", { method: "POST", body: JSON.stringify(body) }),
  startAcquire: (body: { target: string; dry_run?: boolean; prod?: boolean; params?: DatabentoAcquireParams }) =>
    j<Job>("data/acquire", { method: "POST", body: JSON.stringify(body) }),
  acquireTargets: () => j<{ targets: { id: string; label: string; ready: boolean; writes_to: string; supports_prod: boolean }[] }>("data/acquire/targets"),
  jobs: () => j<{ jobs: Job[] }>("data/jobs"),
  job: (id: string) => j<Job>(`data/jobs/${id}`),
  getSchedule: () => j<{ plan: SchedulePlanItem[]; installed: boolean; have_crontab: boolean }>("data/schedule"),
  putSchedule: (schedule: Config["schedule"]) =>
    j<{ plan: SchedulePlanItem[]; installed: boolean }>("data/schedule", { method: "PUT", body: JSON.stringify({ schedule }) }),
  applySchedule: (dry_run = false) => j<{ ok: boolean; installed: boolean; crontab?: string; error?: string }>("data/schedule/apply", { method: "POST", body: JSON.stringify({ dry_run }) }),
  clearSchedule: () => j<{ ok: boolean; error?: string }>("data/schedule/clear", { method: "POST", body: "{}" }),
  explore: () => j<ExploreOverview>("data/explore"),
  // data setup utility
  cancelJob: (id: string) => j<{ ok: boolean; job: Job }>(`data/jobs/${id}/cancel`, { method: "POST", body: "{}" }),
  layout: () => j<Layout>("setup/layout"),
  initLayout: (paths?: Record<string, string>) =>
    j<{ ok: boolean; created: string[]; skipped: { path: string; config_key: string; reason: string }[]; layout: Layout }>(
      "setup/layout/init", { method: "POST", body: JSON.stringify({ paths }) }),
  keys: () => j<KeysView>("setup/keys"),
  saveKey: (vendor: Vendor, key: Partial<VendorKey> & Record<string, unknown>) =>
    j<VendorKey>(`setup/keys/${vendor}`, { method: "POST", body: JSON.stringify(key) }),
  deleteKey: (vendor: Vendor, id: string) => j<{ ok: boolean }>(`setup/keys/${vendor}/${id}`, { method: "DELETE" }),
  testKey: (vendor: Vendor, id: string) =>
    j<{ ok: boolean; error?: string; datasets?: number; note?: string; access?: Record<string, boolean> }>(
      `setup/keys/${vendor}/${id}/test`, { method: "POST", body: "{}" }),
  setupStatus: () => j<SetupStatus>("setup/status"),
  browse: (path?: string | null) => j<BrowseResult>(`setup/browse${path ? `?path=${encodeURIComponent(path)}` : ""}`),
  inspect: (vendor: Vendor, paths: string[]) => j<InspectResult>("setup/inspect", { method: "POST", body: JSON.stringify({ vendor, paths }) }),
  importLocal: (vendor: Vendor, paths: string[], convert = true, jobs = 4, quote_intervals?: QuoteIntervals) =>
    j<Job>("setup/import", { method: "POST", body: JSON.stringify({ vendor, paths, convert, jobs, quote_intervals }) }),
  quote: (vendor: Vendor, params: Record<string, unknown>) =>
    j<DownloadQuote>("setup/download", { method: "POST", body: JSON.stringify({ vendor, params, dry_run: true }) }),
  download: (vendor: Vendor, params: Record<string, unknown>, convert = true, quote_intervals?: QuoteIntervals) =>
    j<Job>("setup/download", { method: "POST", body: JSON.stringify({ vendor, params, dry_run: false, convert, quote_intervals }) }),
  symbols: (store: string, limit = 200) => j<SymbolsResult>(`data/explore/symbols?store=${store}&limit=${limit}`),
};

export type DatabentoAcquireParams = {
  dataset: string;
  schema: string;
  symbols: string | string[];
  start: string;
  end?: string;
  stype_in?: string;
  max_cost?: number;
};
export type SchedulePlanItem = { group: string; enabled: boolean; cron: string; command: string; next_run: string | null };
export type ExploreOverview = {
  storage_root: string;
  storage: Record<string, { partitions?: number; start?: string; end?: string } | boolean>;
  esp: Record<string, { present?: boolean; rows?: number; docs?: number; max_date?: string; error?: string }>;
};
export type SymbolsResult = {
  ok: boolean;
  store?: string;
  total_symbols?: number;
  symbols?: { ticker: string; start: string; end: string; rows: number }[];
  error?: string;
  note?: string;
};

// Subscribe to a job's SSE log stream. Returns an unsubscribe fn.
export function streamJobLogs(
  id: string,
  onLine: (line: string) => void,
  onEnd?: (reason: string) => void,
): () => void {
  const es = new EventSource(`${BASE}/data/jobs/${id}/logs`);
  es.onmessage = (e) => onLine(e.data);
  es.addEventListener("end", (e) => {
    onEnd?.((e as MessageEvent).data);
    es.close();
  });
  es.onerror = () => es.close();
  return () => es.close();
}

// ── data setup utility ─────────────────────────────────────────────────────

export type Vendor = "databento" | "massive";
export type QuoteIntervals = { stock: number; option: number; future: number };
export const QUOTE_INTERVALS = [1, 5, 15, 30, 60] as const;

export type SetupStatus = {
  storage_root: string;
  libraries: Record<Vendor, string>;
  roots: string[];
  credentials: Record<Vendor, boolean>;
  keys?: Record<Vendor, number>;
  massive_endpoint?: string;
  massive_indices: string[];
  quote_intervals: QuoteIntervals;
  today: string;
};

export type BrowseEntry = { name: string; path: string; dir: boolean; size?: number | null; mtime?: number; hint?: string | null };
export type BrowseResult = { path: string | null; parent: string | null; roots: string[]; entries: BrowseEntry[]; truncated?: boolean };

export type InspectResult = {
  vendor: Vendor;
  files: number;
  bytes?: number;
  ignored?: number;
  described?: number;
  convertible_files?: number;
  start?: string;
  end?: string;
  first_error?: string;
  groups: {
    index?: string; asset?: string | null; resolution?: string; dataset?: string; schema?: string; role?: string;
    files: number; csv?: number; bytes?: number; convertible?: boolean; start?: string | null; end?: string | null; errors?: number;
  }[];
};

export type DownloadQuote = {
  ok: boolean;
  error?: string;
  lines?: string[];
  files?: number;
  missing?: number;
  bytes?: number;
  cost_usd?: number;
  [k: string]: unknown;
};
