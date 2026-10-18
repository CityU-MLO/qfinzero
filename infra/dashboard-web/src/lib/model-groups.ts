// Model provider groups for Chat (and anything else that calls a model).
//
// A group is one endpoint with one API type, one key and the models its
// /models endpoint lists. Groups live in this browser's localStorage; keys are
// never sent anywhere except with the requests that use them.

export type ApiType = "openai" | "anthropic" | "antigravity";

export const API_TYPES: readonly ApiType[] = ["openai", "anthropic", "antigravity"];

export const API_META: Record<ApiType, { label: string; zh: string; base: string; hint: [string, string] }> = {
  openai: {
    label: "OpenAI",
    zh: "OpenAI",
    base: "https://api.openai.com/v1",
    hint: ["OpenAI-compatible: base URL ends in /v1 (vLLM, DeepSeek, OpenRouter, …)", "兼容 OpenAI 接口：base URL 以 /v1 结尾（vLLM、DeepSeek、OpenRouter 等）"],
  },
  anthropic: {
    label: "Claude",
    zh: "Claude",
    base: "https://api.anthropic.com",
    hint: ["Anthropic Messages API: base URL without /v1 (as ANTHROPIC_BASE_URL)", "Anthropic Messages API：base URL 不含 /v1（与 ANTHROPIC_BASE_URL 相同）"],
  },
  antigravity: {
    label: "Gemini · Antigravity",
    zh: "Gemini · Antigravity",
    base: "",
    hint: ["Antigravity gateway (Anthropic protocol): e.g. http://host:8081/antigravity", "Antigravity 网关（Anthropic 协议）：例如 http://host:8081/antigravity"],
  },
};

export interface ModelInfo {
  id: string;
  name: string;
}

export interface ModelGroup {
  id: string;
  name: string;
  api: ApiType;
  baseUrl: string;
  apiKey: string;
  models: ModelInfo[];
  fetchedAt?: string;
}

export interface ModelSettings {
  version: 2;
  groups: ModelGroup[];
  active: { groupId: string; model: string } | null;
  proxy: string; // LLM egress proxy; blank = the server default
}

export const STORAGE_KEY = "qfz_model_groups";
const LEGACY_KEY = "qfz_console_settings";
export const CHANGE_EVENT = "qfz-model-groups";

let seq = 0;
export function newId(): string {
  seq += 1;
  return `g${Date.now().toString(36)}${seq.toString(36)}`;
}

export function emptySettings(): ModelSettings {
  return { version: 2, groups: [], active: null, proxy: "" };
}

export function isApiType(x: unknown): x is ApiType {
  return x === "openai" || x === "anthropic" || x === "antigravity";
}

function guessApi(url: string, fallback: ApiType = "openai"): ApiType {
  if (/antigravity/i.test(url)) return "antigravity";
  if (/anthropic/i.test(url)) return "anthropic";
  return fallback;
}

function nameFromUrl(url: string, api: ApiType): string {
  try {
    const u = new URL(url);
    return `${API_META[api].label} · ${u.host}`;
  } catch {
    return API_META[api].label;
  }
}

/** Old single-list settings (before groups) -> groups. */
export function migrateLegacy(raw: unknown): ModelSettings | null {
  const old = raw as { providers?: { id: string; label: string; baseUrl: string; apiKey: string; models: string[] }[]; activeProviderId?: string; activeModel?: string; proxy?: string };
  if (!old?.providers?.length) return null;
  const groups: ModelGroup[] = old.providers
    .filter((p) => p.apiKey || !["openai", "deepseek", "gemini", "claude"].includes(p.id))
    .map((p) => {
      const api: ApiType = p.id === "claude" ? "anthropic" : guessApi(p.baseUrl);
      return {
        id: p.id, name: p.label, api,
        baseUrl: api === "anthropic" ? p.baseUrl.replace(/\/v1\/?$/, "") : p.baseUrl,
        apiKey: p.apiKey, models: (p.models ?? []).map((m) => ({ id: m, name: m })),
      };
    });
  const activeGroup = groups.find((g) => g.id === old.activeProviderId);
  return {
    version: 2, groups, proxy: old.proxy ?? "",
    active: activeGroup && old.activeModel ? { groupId: activeGroup.id, model: old.activeModel } : null,
  };
}

export function loadSettings(): ModelSettings {
  if (typeof window === "undefined") return emptySettings();
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const s = JSON.parse(raw) as ModelSettings;
      return { ...emptySettings(), ...s, groups: (s.groups ?? []).filter((g) => isApiType(g.api)) };
    }
    const legacy = localStorage.getItem(LEGACY_KEY);
    const migrated = legacy ? migrateLegacy(JSON.parse(legacy)) : null;
    return migrated ?? emptySettings();
  } catch {
    return emptySettings();
  }
}

export function saveSettings(s: ModelSettings): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
  window.dispatchEvent(new Event(CHANGE_EVENT)); // same-tab listeners (storage fires only in other tabs)
}

export interface ResolvedModel {
  api: ApiType;
  baseUrl: string;
  apiKey: string;
  model: string;
  groupName: string;
}

export function resolve(s: ModelSettings, groupId?: string, model?: string): ResolvedModel | null {
  const gid = groupId ?? s.active?.groupId;
  const m = model ?? s.active?.model;
  const g = s.groups.find((x) => x.id === gid);
  if (!g || !m) return null;
  return { api: g.api, baseUrl: g.baseUrl, apiKey: g.apiKey, model: m, groupName: g.name };
}

// ── export / import ──────────────────────────────────────────────────────────

export const EXPORT_FORMAT = "qfinzero-model-groups";

export function exportJson(s: ModelSettings, includeKeys: boolean): string {
  const active = s.active ? { group: s.groups.find((g) => g.id === s.active!.groupId)?.name, model: s.active.model } : null;
  return JSON.stringify(
    {
      format: EXPORT_FORMAT,
      version: 1,
      exported_at: new Date().toISOString(),
      groups: s.groups.map((g) => ({
        name: g.name, api: g.api, base_url: g.baseUrl,
        ...(includeKeys ? { api_key: g.apiKey } : {}),
        models: g.models.map((m) => m.id),
      })),
      active,
    },
    null,
    2,
  );
}

export interface Imported {
  groups: Omit<ModelGroup, "id">[];
  active?: { group: string; model: string };
  source: "qfinzero" | "claude-code" | "env" | "codex";
}

function fromQfz(obj: Record<string, unknown>): Imported {
  const groups = (obj.groups as Record<string, unknown>[]).map((g) => {
    const api = isApiType(g.api) ? g.api : guessApi(String(g.base_url ?? g.baseUrl ?? ""));
    const baseUrl = String(g.base_url ?? g.baseUrl ?? API_META[api].base);
    const models = ((g.models as unknown[]) ?? []).map((m) =>
      typeof m === "string" ? { id: m, name: m } : { id: String((m as ModelInfo).id), name: String((m as ModelInfo).name ?? (m as ModelInfo).id) });
    return { name: String(g.name ?? nameFromUrl(baseUrl, api)), api, baseUrl, apiKey: String(g.api_key ?? g.apiKey ?? ""), models };
  });
  const a = obj.active as { group?: string; model?: string } | null;
  return { groups, active: a?.group && a?.model ? { group: a.group, model: a.model } : undefined, source: "qfinzero" };
}

function fromAnthropicEnv(env: Record<string, string>, source: Imported["source"]): Imported {
  const baseUrl = env.ANTHROPIC_BASE_URL || API_META.anthropic.base;
  const api = guessApi(baseUrl, "anthropic");
  const key = env.ANTHROPIC_AUTH_TOKEN || env.ANTHROPIC_API_KEY || "";
  const name = nameFromUrl(baseUrl, api);
  const model = env.ANTHROPIC_MODEL;
  return { groups: [{ name, api, baseUrl, apiKey: key, models: [] }], active: model ? { group: name, model } : undefined, source };
}

/** ``export KEY="v"`` / ``KEY=v`` lines. */
function parseEnvLines(text: string): Record<string, string> {
  const env: Record<string, string> = {};
  for (const line of text.split(/\r?\n/)) {
    const m = /^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$/.exec(line);
    if (m) env[m[1]] = m[2].replace(/^(['"])(.*)\1$/, "$2");
  }
  return env;
}

/** Minimal TOML reader for Codex's config.toml: top-level keys and [model_providers.X] tables. */
function parseCodexToml(text: string): Imported | null {
  const top: Record<string, string> = {};
  const providers: Record<string, Record<string, string>> = {};
  let section: string | null = null;
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.replace(/\s+#.*$/, "").trim();
    if (!line || line.startsWith("#")) continue;
    const sec = /^\[([^\]]+)\]$/.exec(line);
    if (sec) {
      section = sec[1].trim();
      continue;
    }
    const kv = /^([A-Za-z0-9_.-]+)\s*=\s*(.+)$/.exec(line);
    if (!kv) continue;
    const value = kv[2].trim().replace(/^"(.*)"$/, "$1").replace(/^'(.*)'$/, "$1");
    if (section === null) top[kv[1]] = value;
    else if (section.startsWith("model_providers.")) {
      const id = section.slice("model_providers.".length).replace(/^"(.*)"$/, "$1");
      (providers[id] ??= {})[kv[1]] = value;
    }
  }
  const ids = Object.keys(providers);
  if (!ids.length) return null;
  const groups = ids.map((id) => {
    const p = providers[id];
    const baseUrl = p.base_url ?? API_META.openai.base;
    return {
      name: p.name ?? id, api: guessApi(baseUrl, "openai"), baseUrl,
      apiKey: p.experimental_bearer_token ?? p.api_key ?? "", models: [],
    };
  });
  const activeId = top.model_provider;
  const activeName = activeId ? providers[activeId]?.name ?? activeId : undefined;
  return {
    groups,
    active: activeName && top.model ? { group: activeName, model: top.model } : undefined,
    source: "codex",
  };
}

/**
 * Parse pasted or uploaded configuration: a QFinZero export, a Claude Code
 * settings.json, shell ``export ANTHROPIC_*`` lines, or a Codex config.toml.
 * Throws with a readable message when nothing is recognised.
 */
export function parseImport(text: string): Imported {
  const trimmed = text.trim();
  if (!trimmed) throw new Error("empty input");
  if (trimmed.startsWith("{")) {
    let obj: Record<string, unknown>;
    try {
      obj = JSON.parse(trimmed);
    } catch (e) {
      throw new Error(`invalid JSON: ${(e as Error).message}`);
    }
    if (Array.isArray(obj.groups)) return fromQfz(obj);
    const env = (obj.env ?? {}) as Record<string, string>;
    if (env.ANTHROPIC_BASE_URL || env.ANTHROPIC_AUTH_TOKEN || env.ANTHROPIC_API_KEY) {
      return fromAnthropicEnv({ ...env, ...(typeof obj.model === "string" ? { ANTHROPIC_MODEL: obj.model } : {}) }, "claude-code");
    }
    throw new Error("JSON is neither a QFinZero export nor a Claude Code settings file");
  }
  const toml = parseCodexToml(trimmed);
  if (toml) return toml;
  const env = parseEnvLines(trimmed);
  if (env.ANTHROPIC_BASE_URL || env.ANTHROPIC_AUTH_TOKEN || env.ANTHROPIC_API_KEY) return fromAnthropicEnv(env, "env");
  if (env.OPENAI_BASE_URL || env.OPENAI_API_KEY) {
    const baseUrl = env.OPENAI_BASE_URL || API_META.openai.base;
    return { groups: [{ name: nameFromUrl(baseUrl, "openai"), api: "openai", baseUrl, apiKey: env.OPENAI_API_KEY ?? "", models: [] }], source: "env" };
  }
  throw new Error("nothing recognised: paste a QFinZero export, a Claude Code settings.json, export lines or a Codex config.toml");
}

/** Add imported groups; a group with the same API type and base URL is updated in place. */
export function mergeImport(s: ModelSettings, imp: Imported): ModelSettings {
  const groups = [...s.groups];
  const ids: Record<string, string> = {};
  for (const g of imp.groups) {
    const same = groups.findIndex((x) => x.api === g.api && x.baseUrl.replace(/\/$/, "") === g.baseUrl.replace(/\/$/, ""));
    if (same >= 0) {
      groups[same] = { ...groups[same], name: g.name || groups[same].name, apiKey: g.apiKey || groups[same].apiKey,
                       models: g.models.length ? g.models : groups[same].models };
      ids[g.name] = groups[same].id;
    } else {
      const id = newId();
      groups.push({ ...g, id });
      ids[g.name] = id;
    }
  }
  const active = imp.active && ids[imp.active.group] ? { groupId: ids[imp.active.group], model: imp.active.model } : s.active;
  return { ...s, groups, active };
}
