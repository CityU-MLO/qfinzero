// Client helpers for the hub's /auth API (same origin). When the console runs
// without the hub (plain `next dev`), /auth is absent and these resolve to
// "no auth" so the UI still works.

export type Role = "viewer" | "researcher" | "admin";
export type Me = { id: number; username: string; role: Role; display_name: string };
export type AuthStatus = { mode: string; has_users: boolean; setup_required: boolean };
export type ApiKey = { id: number; name: string; prefix: string; created_at: number;
  last_used_at: number | null; revoked: boolean; username?: string };
export type UserRow = Me & { disabled: boolean; created_at: number; last_login_at: number | null };

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  const text = await res.text();
  let data: unknown = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text };
  }
  if (!res.ok) {
    const d = data as { detail?: unknown; error?: string };
    const msg = typeof d.detail === "string" ? d.detail : d.error ?? `HTTP ${res.status}`;
    throw Object.assign(new Error(msg), { status: res.status });
  }
  return data as T;
}

export const auth = {
  status: () => call<AuthStatus>("/auth/status"),
  me: async (): Promise<Me | null> => {
    try {
      return (await call<{ user: Me }>("/auth/me")).user;
    } catch {
      return null;
    }
  },
  login: (username: string, password: string) =>
    call<{ user: Me }>("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  setup: (token: string, username: string, password: string) =>
    call<{ user: Me }>("/auth/setup", { method: "POST", body: JSON.stringify({ token, username, password }) }),
  logout: () => call<{ ok: boolean }>("/auth/logout", { method: "POST" }),
  changePassword: (current_password: string, new_password: string) =>
    call("/auth/password", { method: "POST", body: JSON.stringify({ current_password, new_password }) }),
  keys: () => call<{ keys: ApiKey[] }>("/auth/keys"),
  createKey: (name: string) =>
    call<{ key: ApiKey; token: string }>("/auth/keys", { method: "POST", body: JSON.stringify({ name }) }),
  revokeKey: (id: number) => call(`/auth/keys/${id}`, { method: "DELETE" }),
  users: () => call<{ users: UserRow[]; roles: Role[]; keys: ApiKey[] }>("/auth/users"),
  createUser: (body: { username: string; password: string; role: Role; display_name?: string }) =>
    call("/auth/users", { method: "POST", body: JSON.stringify(body) }),
  updateUser: (id: number, body: Partial<{ role: Role; disabled: boolean; password: string }>) =>
    call(`/auth/users/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteUser: (id: number) => call(`/auth/users/${id}`, { method: "DELETE" }),
};

/** Only allow same-site relative redirect targets after login. */
export function safeNext(next: string | null | undefined, fallback = "/chat"): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/login")) {
    return fallback;
  }
  return next;
}

export const ROLE_LABEL: Record<Role, string> = {
  viewer: "Viewer",
  researcher: "Researcher",
  admin: "Admin",
};
