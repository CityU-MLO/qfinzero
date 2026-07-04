// Typed client for the data-admin service (via the /api/data-admin proxy).

const BASE = "/api/data-admin";

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}/${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok) throw new Error((data && data.error) || `HTTP ${res.status}`);
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

export type Job = {
  id: string;
  kind: string;
  label: string;
  status: "queued" | "running" | "done" | "error";
  error?: string | null;
  n_lines?: number;
  lines?: string[];
  result?: unknown;
};

export type ScanResult = {
  provider: string;
  ok: boolean;
  s3?: { ok: boolean; error?: string; datasets?: { name: string; required: boolean; label: string }[]; missing_required?: string[] };
  rest?: { ok: boolean; error?: string; status?: string };
  tushare?: { ok: boolean; error?: string; rows?: number };
};

export const dataAdmin = {
  setupState: () => j<SetupState>("data/setup-state"),
  getConfig: () => j<Config>("data/config"),
  putConfig: (patch: Partial<Config>) => j<Config>("data/config", { method: "PUT", body: JSON.stringify(patch) }),
  scan: (provider: string) => j<ScanResult>("data/scan", { method: "POST", body: JSON.stringify({ provider }) }),
  sources: () => j<{ sources: Source[] }>("data/status"),
  startUpdate: (body: { source?: string; market?: string | null; dry_run?: boolean; force?: boolean }) =>
    j<Job>("data/update", { method: "POST", body: JSON.stringify(body) }),
  startAcquire: (body: { target: string; dry_run?: boolean; prod?: boolean }) =>
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
  symbols: (store: string, limit = 200) => j<SymbolsResult>(`data/explore/symbols?store=${store}&limit=${limit}`),
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
