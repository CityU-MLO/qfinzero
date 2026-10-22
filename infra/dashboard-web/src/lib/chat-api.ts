// Client for the playground conversations (/api/playground/*).

export type ToolStatus = "pending" | "running" | "done" | "error" | "cancelled";

export interface ToolCall {
  id: string;
  tool: string;
  input?: Record<string, unknown>;
  output?: unknown;
  error?: string;
  status: ToolStatus;
  started_at?: number; // ms epoch
  ended_at?: number;
}

export interface Step {
  text: string;
  tool_calls: ToolCall[];
  started_at?: number;
  ended_at?: number | null;
  usage?: { input_tokens?: number | null; output_tokens?: number | null } | null;
  /** The model call failed for a moment and is waiting to start again. */
  retry?: { attempt: number; of: number; delay_s: number; error?: string } | null;
  /** Retries this step needed before it went through. */
  retries?: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  steps: Step[];
  status: "complete" | "interrupted" | "error" | "running";
  error?: string | null;
  model?: string | null;
  usage?: { input_tokens?: number | null; output_tokens?: number | null } | null;
  created_at: number; // s epoch
  finished_at?: number | null;
  seq?: number;
}

export interface ThreadSummary {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  model?: string | null;
  as_of?: string | null;
  message_count?: number;
  running?: boolean;
}

export interface ThreadDetail {
  thread: ThreadSummary & { summary?: string | null; summary_through?: number };
  messages: ChatMessage[];
  running: boolean;
  live: ChatMessage | null;
}

export interface ContextUsage {
  budget: number;
  system: number;
  summary: number;
  messages: number;
  total: number;
  messages_in_context: number;
  compacted_messages: number;
  last_input_tokens?: number | null;
}

export interface LlmFields {
  api: string;
  model: string;
  base_url: string;
  api_key: string;
  proxy?: string;
}

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api/playground/${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((body as { detail?: string }).detail ?? `HTTP ${r.status}`);
  return body as T;
}

export const chatApi = {
  list: (q = "") => j<{ threads: ThreadSummary[] }>(`threads${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  create: () => j<ThreadSummary>("threads", { method: "POST", body: "{}" }),
  get: (id: string) => j<ThreadDetail>(`threads/${id}`),
  rename: (id: string, title: string) => j<ThreadSummary>(`threads/${id}`, { method: "PATCH", body: JSON.stringify({ title }) }),
  remove: (id: string) => j<{ ok: boolean }>(`threads/${id}`, { method: "DELETE" }),
  interrupt: (id: string) => j<{ ok: boolean }>(`threads/${id}/interrupt`, { method: "POST", body: "{}" }),
  context: (id: string, budget: number, asOf: string) =>
    j<ContextUsage>(`threads/${id}/context?budget=${budget}&as_of=${encodeURIComponent(asOf)}`),
  compact: (id: string, llm: LlmFields) =>
    j<{ ok: boolean; error?: string; compacted_messages?: number }>(`threads/${id}/compact`, {
      method: "POST", body: JSON.stringify(llm),
    }),
  exportUrl: (id: string, tools = true) => `/api/playground/threads/${id}/export?tools=${tools}`,
};

export type StreamEvent = { type: string; [k: string]: unknown };

/** POST /chat and call ``onEvent`` for each SSE event until the stream ends. */
export async function streamChat(body: Record<string, unknown>, onEvent: (e: StreamEvent) => void,
                                 signal?: AbortSignal): Promise<void> {
  const res = await fetch("/api/playground/chat", {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body), signal,
  });
  if (!res.ok || !res.body) {
    const b = await res.json().catch(() => ({}));
    let detail = (b as { detail?: string }).detail ?? "";
    try { detail = JSON.parse(detail).detail ?? detail; } catch { /* plain text */ }
    throw new Error(detail || `HTTP ${res.status}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      try {
        onEvent(JSON.parse(line.slice(6)));
      } catch {
        /* keep-alive or partial line */
      }
    }
  }
}

/** Fold one stream event into the assistant message being built. */
export function applyEvent(m: ChatMessage, e: StreamEvent): ChatMessage {
  const steps = m.steps.map((s) => ({ ...s, tool_calls: [...s.tool_calls] }));
  const at = (i: unknown) => {
    const idx = typeof i === "number" ? i : steps.length - 1;
    while (steps.length <= idx) steps.push({ text: "", tool_calls: [] });
    return steps[idx];
  };
  switch (e.type) {
    case "step_start": {
      const s = at(e.step);
      s.started_at = e.t as number;
      if (e.restart) s.text = "";
      break;
    }
    case "retry":
      at(e.step).retry = { attempt: e.attempt as number, of: e.of as number, delay_s: e.delay_s as number, error: e.error as string };
      break;
    case "llm_chunk":
      at(e.step).text += e.content as string;
      break;
    case "step_end": {
      const s = at(e.step);
      s.text = (e.text as string) || s.text;
      s.ended_at = e.t as number;
      if (s.retry) {
        s.retries = s.retry.attempt;
        s.retry = null;
      }
      s.tool_calls = (e.tool_calls as ToolCall[]) ?? s.tool_calls;
      break;
    }
    case "tool_start":
    case "tool_end": {
      const s = at(e.step);
      const i = s.tool_calls.findIndex((c) => c.id === e.id);
      const prev = i >= 0 ? s.tool_calls[i] : { id: e.id as string, tool: e.tool as string, status: "pending" as ToolStatus };
      const next: ToolCall = e.type === "tool_start"
        ? { ...prev, input: (e.input as Record<string, unknown>) ?? prev.input, status: "running", started_at: e.t as number }
        : { ...prev, output: e.output, status: (e.status as ToolStatus) ?? "done", ended_at: e.t as number };
      if (i >= 0) s.tool_calls[i] = next; else s.tool_calls.push(next);
      break;
    }
    default:
      return m;
  }
  return { ...m, steps, content: steps.map((s) => s.text).filter(Boolean).join("\n\n") };
}

export const fmtTokens = (n: number | null | undefined) =>
  n == null ? "—" : n >= 1000 ? `${(n / 1000).toFixed(n >= 100_000 ? 0 : 1)}k` : String(n);

export function callMs(c: ToolCall): number | null {
  return c.started_at && c.ended_at ? c.ended_at - c.started_at : null;
}
