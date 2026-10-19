"use client";

// API key manager shared by the account page (your own keys) and the users
// admin page (keys issued to anyone). A key is narrowed from its owner's role
// by scopes, read-only, an expiry and a rate limit; the token is shown once,
// with ready-to-paste snippets.

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronDown, ChevronRight, Copy, KeyRound, Loader2, Pencil, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Segmented } from "@/components/ui/segmented";
import { useT } from "@/components/locale-provider";
import { auth, ROLE_RANK, type ApiKey, type KeySettings, type Role, type Scope, type UserRow } from "@/lib/auth";

const input =
  "w-full rounded-md border border-input bg-card px-3 py-2 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/20";
const small = "rounded-md border border-input bg-card px-2 py-1.5 text-sm outline-none focus:border-ring";

const SCOPE_TEXT: Record<string, [string, string]> = {
  "market-data": ["Market data", "行情数据"],
  events: ["Events & news", "事件与新闻"],
  trading: ["Paper trading", "模拟交易"],
  mcp: ["MCP", "MCP"],
  chat: ["Chat", "对话助手"],
  admin: ["Admin", "管理"],
};
const SCOPE_DESC_ZH: Record<string, string> = {
  "market-data": "UPQ 行情、报价、期权链、期货",
  events: "ESP 新闻、财报与宏观事件",
  trading: "模拟券商账户、会话与订单",
  mcp: "MCP 端点；可用工具取决于密钥的其他权限",
  chat: "对话助手",
  admin: "数据管理与用户管理",
};

type Preset = { id: string; en: string; zh: string; scopes: string[] | null; read_only: boolean; min: Role };
const PRESETS: Preset[] = [
  { id: "reader", en: "Data reader", zh: "只读数据", scopes: ["market-data", "events"], read_only: true, min: "viewer" },
  { id: "agent", en: "MCP agent", zh: "MCP agent", scopes: ["mcp", "market-data", "events", "trading"], read_only: false, min: "researcher" },
  { id: "bot", en: "Trading bot", zh: "交易脚本", scopes: ["market-data", "trading"], read_only: false, min: "researcher" },
  { id: "full", en: "Full access", zh: "完整权限", scopes: null, read_only: false, min: "viewer" },
];
const EXPIRY = [7, 30, 90, 365];
const RATES = [60, 600, 3000];

function when(ts: number | null, never: string) {
  return ts ? new Date(ts * 1000).toLocaleString() : never;
}

function ago(ts: number | null, t: (en: string, zh: string) => string) {
  if (!ts) return t("never", "从未");
  const s = Date.now() / 1000 - ts;
  if (s < 90) return t("just now", "刚刚");
  if (s < 5400) return t(`${Math.round(s / 60)} min ago`, `${Math.round(s / 60)} 分钟前`);
  if (s < 129600) return t(`${Math.round(s / 3600)} h ago`, `${Math.round(s / 3600)} 小时前`);
  return t(`${Math.round(s / 86400)} d ago`, `${Math.round(s / 86400)} 天前`);
}

export function CopyButton({ text, className = "" }: { text: string; className?: string }) {
  const t = useT();
  const [done, setDone] = useState(false);
  return (
    <button type="button" className={`inline-flex items-center gap-1 rounded-md border bg-card px-2 py-1 text-xs hover:bg-accent ${className}`}
            onClick={() => navigator.clipboard.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1500); })}>
      {done ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />} {done ? t("Copied", "已复制") : t("Copy", "复制")}
    </button>
  );
}

export function useOrigin() {
  const [origin, setOrigin] = useState("https://your-host");
  useEffect(() => setOrigin(window.location.origin), []);
  return origin;
}

// ── snippets ─────────────────────────────────────────────────────────────

type SnippetKind = "env" | "curl" | "python" | "mcp";

export function snippets(origin: string, token: string, scopes: string[] | null): Record<SnippetKind, string> {
  const has = (s: string) => scopes === null || scopes.includes(s);
  const path = has("market-data") ? "/svc/upq/stock/daily?tickers=SPY&start=2025-01-02&end=2025-01-10"
    : has("events") ? "/svc/esp/esp/news/counts" : has("trading") ? "/svc/pmb/v1/accounts" : "/auth/me";
  return {
    env: `export QFZ_URL=${origin}\nexport QFZ_API_KEY=${token}`,
    curl: `curl -s "$QFZ_URL${path}" \\\n  -H "Authorization: Bearer $QFZ_API_KEY"`,
    python: `import os, requests\n\nqfz = requests.Session()\nqfz.headers["Authorization"] = f"Bearer {os.environ['QFZ_API_KEY']}"\n` +
      `r = qfz.get(os.environ["QFZ_URL"] + "${path.split("?")[0]}"${path.includes("?") ? `,\n            params=${pyParams(path)}` : ""})\nr.raise_for_status()\nprint(r.json())`,
    mcp: JSON.stringify({ mcpServers: { qfinzero: { url: `${origin}/mcp/`, headers: { Authorization: `Bearer ${token}` } } } }, null, 2),
  };
}

function pyParams(path: string) {
  const q = new URLSearchParams(path.split("?")[1]);
  return "{" + [...q.entries()].map(([k, v]) => `"${k}": "${v}"`).join(", ") + "}";
}

export function SnippetBlock({ origin, token, scopes }: { origin: string; token: string; scopes: string[] | null }) {
  const t = useT();
  const all = useMemo(() => snippets(origin, token, scopes), [origin, token, scopes]);
  const mcpOk = scopes === null || scopes.includes("mcp");
  const [kind, setKind] = useState<SnippetKind>(mcpOk ? "mcp" : "env");
  const opts = [
    { value: "env" as const, label: t("Env", "环境变量") },
    { value: "curl" as const, label: "curl" },
    { value: "python" as const, label: "Python" },
    ...(mcpOk ? [{ value: "mcp" as const, label: t("MCP config", "MCP 配置") }] : []),
  ];
  return (
    <div className="space-y-2">
      <Segmented value={kind} onChange={setKind} options={opts} />
      <div className="relative">
        <pre className="max-h-64 overflow-auto rounded-lg bg-muted p-3 pr-20 font-mono text-[12px] leading-relaxed text-foreground">{all[kind]}</pre>
        <CopyButton text={all[kind]} className="absolute right-2 top-2" />
      </div>
    </div>
  );
}

// ── create ───────────────────────────────────────────────────────────────

function ScopePicker({ scopes, value, onChange, ownerRole }: {
  scopes: Scope[]; value: string[] | null; onChange: (v: string[] | null) => void; ownerRole: Role;
}) {
  const t = useT();
  const allowed = (s: Scope) => ROLE_RANK[ownerRole] >= ROLE_RANK[s.min_role];
  const chosen = value ?? scopes.filter(allowed).map((s) => s.id);
  return (
    <div className="grid gap-1.5 sm:grid-cols-2">
      {scopes.map((s) => {
        const ok = allowed(s);
        const [en, zh] = SCOPE_TEXT[s.id] ?? [s.id, s.id];
        return (
          <label key={s.id} className={`flex cursor-pointer items-start gap-2 rounded-md border px-2.5 py-2 text-sm ${ok ? "hover:bg-accent/50" : "cursor-not-allowed opacity-50"} ${chosen.includes(s.id) && ok ? "border-primary/40 bg-primary/5" : ""}`}
                 title={ok ? s.paths.join("  ") : t(`Needs the ${s.min_role} role`, `需要${s.min_role}角色`)}>
            <input type="checkbox" className="mt-0.5" disabled={!ok} checked={ok && chosen.includes(s.id)}
                   onChange={(e) => onChange(e.target.checked ? [...chosen, s.id] : chosen.filter((x) => x !== s.id))} />
            <span>
              <span className="font-medium">{t(en, zh)}</span>
              <span className="block text-xs text-muted-foreground">{t(s.description, SCOPE_DESC_ZH[s.id] ?? s.description)}</span>
            </span>
          </label>
        );
      })}
    </div>
  );
}

function ExpiryPicker({ days, date, onChange }: { days: number | null; date: string; onChange: (d: number | null, date: string) => void }) {
  const t = useT();
  const v = date ? "date" : days === null ? "never" : String(days);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <select className={small} value={v} onChange={(e) => {
        const x = e.target.value;
        if (x === "never") onChange(null, "");
        else if (x === "date") onChange(null, new Date(Date.now() + 30 * 864e5).toISOString().slice(0, 10));
        else onChange(Number(x), "");
      }}>
        <option value="never">{t("Never expires", "永不过期")}</option>
        {EXPIRY.map((d) => <option key={d} value={d}>{t(`${d} days`, `${d} 天`)}</option>)}
        <option value="date">{t("On a date…", "指定日期…")}</option>
      </select>
      {date && <input type="date" className={small} value={date} min={new Date().toISOString().slice(0, 10)} onChange={(e) => onChange(null, e.target.value)} />}
    </div>
  );
}

function RatePicker({ value, onChange }: { value: number | null; onChange: (v: number | null) => void }) {
  const t = useT();
  const preset = value === null || RATES.includes(value);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <select className={small} value={value === null ? "none" : preset ? String(value) : "custom"}
              onChange={(e) => onChange(e.target.value === "none" ? null : e.target.value === "custom" ? 120 : Number(e.target.value))}>
        <option value="none">{t("No limit", "不限速")}</option>
        {RATES.map((r) => <option key={r} value={r}>{t(`${r} / min`, `${r} 次/分钟`)}</option>)}
        <option value="custom">{t("Custom…", "自定义…")}</option>
      </select>
      {!preset && <input type="number" min={1} max={100000} className={`${small} w-28`} value={value ?? ""}
                         onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)} />}
    </div>
  );
}

export function CreateKey({ ownerRole, users, onCreated }: {
  ownerRole: Role; users?: UserRow[]; onCreated: (r: { key: ApiKey; token: string }) => void;
}) {
  const t = useT();
  const sq = useQuery({ queryKey: ["auth", "scopes"], queryFn: auth.scopes });
  const [owner, setOwner] = useState<number | "">("");
  const role: Role = users && owner !== "" ? users.find((u) => u.id === owner)?.role ?? "viewer" : ownerRole;
  const [f, setF] = useState({ name: "", scopes: null as string[] | null, read_only: false, days: 90 as number | null,
    date: "", rate: null as number | null, note: "", preset: "full" });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const scopes = sq.data?.scopes ?? [];
  const usable = PRESETS.filter((p) => ROLE_RANK[role] >= ROLE_RANK[p.min]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setBusy(true);
    const body: KeySettings = { name: f.name || "key", scopes: f.scopes, read_only: f.read_only, rate_per_min: f.rate, note: f.note,
      ...(f.date ? { expires_at: f.date } : { expires_in_days: f.days }) };
    try {
      const r = users && owner !== "" ? await auth.issueKey(owner, body) : await auth.createKey(body);
      onCreated(r);
      setF({ ...f, name: "", note: "" });
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1 text-sm">
          <span className="text-xs font-medium text-muted-foreground">{t("Name", "名称")}</span>
          <input className={input} placeholder={t("e.g. eval-runner", "例如 eval-runner")} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        </label>
        {users && (
          <label className="space-y-1 text-sm">
            <span className="text-xs font-medium text-muted-foreground">{t("Issue to", "发放给")}</span>
            <select className={input} value={owner} onChange={(e) => setOwner(e.target.value ? Number(e.target.value) : "")}>
              <option value="">{t("Myself", "我自己")}</option>
              {users.filter((u) => !u.disabled).map((u) => <option key={u.id} value={u.id}>{u.username} · {u.role}</option>)}
            </select>
          </label>
        )}
      </div>
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground">{t("Access", "权限")}</span>
          {usable.map((p) => (
            <button type="button" key={p.id}
                    className={`rounded-full border px-2.5 py-0.5 text-xs ${f.preset === p.id ? "border-primary bg-primary/10 text-primary" : "hover:bg-accent"}`}
                    onClick={() => setF({ ...f, preset: p.id, scopes: p.scopes, read_only: p.read_only })}>{t(p.en, p.zh)}</button>
          ))}
        </div>
        {sq.isLoading ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /> :
          <ScopePicker scopes={scopes} value={f.scopes} ownerRole={role}
                       onChange={(v) => setF({ ...f, scopes: v, preset: "" })} />}
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={f.read_only} onChange={(e) => setF({ ...f, read_only: e.target.checked, preset: "" })} />
          {t("Read-only: queries only; no orders, sessions, chat or state-changing MCP tools", "只读：仅能查询；不能下单、建会话、对话或调用会改变状态的 MCP 工具")}
        </label>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <span className="text-xs font-medium text-muted-foreground">{t("Expires", "到期")}</span>
          <ExpiryPicker days={f.days} date={f.date} onChange={(d, date) => setF({ ...f, days: d, date })} />
        </div>
        <div className="space-y-1">
          <span className="text-xs font-medium text-muted-foreground">{t("Rate limit", "速率限制")}</span>
          <RatePicker value={f.rate} onChange={(rate) => setF({ ...f, rate })} />
        </div>
      </div>
      <input className={input} placeholder={t("Note (optional): who it's for, where it runs", "备注（可选）：给谁用、在哪里运行")} value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} />
      {err && <p className="text-sm text-destructive">{err}</p>}
      <button disabled={busy || (f.scopes !== null && f.scopes.length === 0)}
              className="flex h-9 items-center gap-1.5 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60">
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />} {t("Create key", "创建密钥")}
      </button>
    </form>
  );
}

export function FreshToken({ fresh, onDismiss }: { fresh: { key: ApiKey; token: string }; onDismiss: () => void }) {
  const t = useT();
  const origin = useOrigin();
  return (
    <div className="space-y-3 rounded-lg border border-success/30 bg-success/5 p-4">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-semibold text-success">
          {t("New key", "新密钥")} “{fresh.key.name}”{fresh.key.username ? ` · ${fresh.key.username}` : ""}
          {t(": copy it now, it will not be shown again.", "：请立即复制，之后将不再显示。")}
        </p>
        <button type="button" onClick={onDismiss} className="text-xs text-muted-foreground hover:text-foreground">{t("Done", "完成")}</button>
      </div>
      <div className="flex items-center gap-2">
        <code className="flex-1 overflow-x-auto rounded-md bg-card px-2 py-1.5 font-mono text-xs">{fresh.token}</code>
        <CopyButton text={fresh.token} />
      </div>
      <SnippetBlock origin={origin} token={fresh.token} scopes={fresh.key.scopes} />
    </div>
  );
}

// ── list ─────────────────────────────────────────────────────────────────

function UsageBars({ k }: { k: ApiKey }) {
  const t = useT();
  const days = useMemo(() => {
    const by = new Map((k.usage ?? []).map((u) => [u.day, u]));
    return Array.from({ length: 14 }, (_, i) => {
      const d = new Date(Date.now() - (13 - i) * 864e5).toISOString().slice(0, 10);
      return { day: d, requests: by.get(d)?.requests ?? 0, denied: by.get(d)?.denied ?? 0 };
    });
  }, [k.usage]);
  const max = Math.max(1, ...days.map((d) => d.requests));
  return (
    <div className="flex items-end gap-px" style={{ height: 22 }} title={t("Requests per day, last 14 days", "最近 14 天每日请求数")}>
      {days.map((d) => (
        <div key={d.day} className="w-1.5 rounded-sm bg-primary/15" style={{ height: "100%" }} title={`${d.day}: ${d.requests}${d.denied ? ` (${d.denied} ${t("denied", "被拒")})` : ""}`}>
          <div className="w-full rounded-sm bg-primary/70" style={{ height: `${(d.requests / max) * 100}%`, marginTop: `${(1 - d.requests / max) * 22}px` }} />
        </div>
      ))}
    </div>
  );
}

function ScopeBadges({ k }: { k: ApiKey }) {
  const t = useT();
  return (
    <div className="flex flex-wrap gap-1">
      {k.scopes === null ? <Badge variant="secondary">{t("all scopes", "全部权限")}</Badge>
        : k.scopes.map((s) => <Badge key={s} variant="outline">{t(...(SCOPE_TEXT[s] ?? [s, s]))}</Badge>)}
      {k.read_only && <Badge variant="warn">{t("read-only", "只读")}</Badge>}
      {k.rate_per_min && <Badge variant="outline">{k.rate_per_min}/min</Badge>}
    </div>
  );
}

function EditKey({ k, ownerRole, onSaved }: { k: ApiKey; ownerRole: Role; onSaved: () => void }) {
  const t = useT();
  const sq = useQuery({ queryKey: ["auth", "scopes"], queryFn: auth.scopes });
  const [f, setF] = useState({ name: k.name, scopes: k.scopes, read_only: k.read_only, rate: k.rate_per_min, note: k.note,
    date: k.expires_at ? new Date(k.expires_at * 1000).toISOString().slice(0, 10) : "", days: null as number | null });
  const [err, setErr] = useState("");
  const save = async () => {
    setErr("");
    try {
      await auth.updateKey(k.id, { name: f.name, scopes: f.scopes, read_only: f.read_only, rate_per_min: f.rate, note: f.note,
        ...(f.days ? { expires_in_days: f.days } : { expires_at: f.date || null }) });
      onSaved();
    } catch (x) {
      setErr((x as Error).message);
    }
  };
  return (
    <div className="space-y-3 bg-secondary/30 p-3">
      <div className="grid gap-2 sm:grid-cols-2">
        <input className={input} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        <input className={input} placeholder={t("Note", "备注")} value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} />
      </div>
      <ScopePicker scopes={sq.data?.scopes ?? []} value={f.scopes} ownerRole={ownerRole} onChange={(v) => setF({ ...f, scopes: v })} />
      <div className="flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.read_only} onChange={(e) => setF({ ...f, read_only: e.target.checked })} />{t("Read-only", "只读")}</label>
        <ExpiryPicker days={f.days} date={f.date} onChange={(d, date) => setF({ ...f, days: d, date })} />
        <RatePicker value={f.rate} onChange={(rate) => setF({ ...f, rate })} />
        <button type="button" onClick={save} className="h-8 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground hover:bg-primary/90">{t("Save", "保存")}</button>
      </div>
      {err && <p className="text-sm text-destructive">{err}</p>}
    </div>
  );
}

export function KeyTable({ keys, showOwner, roleOf, onChanged }: {
  keys: ApiKey[]; showOwner?: boolean; roleOf: (k: ApiKey) => Role; onChanged: () => void;
}) {
  const t = useT();
  const [open, setOpen] = useState<number | null>(null);
  const [edit, setEdit] = useState<number | null>(null);
  const [showOld, setShowOld] = useState(false);
  const live = keys.filter((k) => !k.revoked);
  const rows = showOld ? keys : live;
  const revoke = async (k: ApiKey) => {
    if (!window.confirm(t(`Revoke ${k.name} (${k.prefix})? Anything using it stops working.`, `吊销 ${k.name}（${k.prefix}）？使用它的程序将立即失效。`))) return;
    await auth.revokeKey(k.id);
    onChanged();
  };
  const cols = showOwner ? 6 : 5;
  return (
    <div className="space-y-2">
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="bg-secondary/50 text-left text-xs text-muted-foreground">
            <tr>
              {showOwner && <th className="px-3 py-2">{t("Owner", "所有者")}</th>}
              <th className="px-3 py-2">{t("Key", "密钥")}</th>
              <th className="px-3 py-2">{t("Access", "权限")}</th>
              <th className="px-3 py-2">{t("Usage (14 d)", "用量（14 天）")}</th>
              <th className="px-3 py-2">{t("Expires", "到期")}</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={cols} className="px-3 py-4 text-center text-muted-foreground">{t("No keys yet.", "暂无密钥。")}</td></tr>}
            {rows.map((k) => {
              const dead = k.revoked || k.expired;
              return [
                <tr key={k.id} className={`border-t align-top ${dead ? "opacity-60" : ""}`}>
                  {showOwner && <td className="px-3 py-2">{k.username}</td>}
                  <td className="px-3 py-2">
                    <button type="button" className="flex items-center gap-1 font-medium" onClick={() => setOpen(open === k.id ? null : k.id)}>
                      {open === k.id ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}{k.name}
                    </button>
                    <span className="block pl-[18px] font-mono text-xs text-muted-foreground">{k.prefix}_…</span>
                  </td>
                  <td className="px-3 py-2"><ScopeBadges k={k} /></td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <UsageBars k={k} />
                      <span className="text-xs tabular-nums text-muted-foreground">{(k.requests_total ?? 0).toLocaleString()}</span>
                    </div>
                    <span className="text-[11px] text-muted-foreground">{t("last used", "最近使用")} {ago(k.last_used_at, t)}</span>
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {k.revoked ? <Badge variant="danger">{t("revoked", "已吊销")}</Badge>
                      : k.expired ? <Badge variant="danger">{t("expired", "已过期")}</Badge>
                      : k.expires_at ? new Date(k.expires_at * 1000).toLocaleDateString() : <span className="text-muted-foreground">{t("never", "永不")}</span>}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right">
                    {!k.revoked && <>
                      <button onClick={() => setEdit(edit === k.id ? null : k.id)} className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs hover:bg-accent"><Pencil className="h-3.5 w-3.5" />{t("Edit", "编辑")}</button>
                      <button onClick={() => revoke(k)} className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-destructive hover:bg-destructive/10"><Trash2 className="h-3.5 w-3.5" />{t("Revoke", "吊销")}</button>
                    </>}
                  </td>
                </tr>,
                open === k.id && (
                  <tr key={`${k.id}-d`} className="border-t bg-secondary/20 text-xs text-muted-foreground">
                    <td colSpan={cols} className="px-3 py-2">
                      <div className="grid gap-x-6 gap-y-1 sm:grid-cols-3">
                        <span>{t("Created", "创建")}: {when(k.created_at, "")}{k.created_by ? ` · ${t("by", "由")} ${k.created_by}` : ""}</span>
                        <span>{t("Last used", "最近使用")}: {when(k.last_used_at, t("never", "从未"))}</span>
                        <span>{t("Denied (14 d)", "被拒（14 天）")}: {(k.usage ?? []).reduce((a, u) => a + u.denied, 0)}</span>
                        {k.note && <span className="sm:col-span-3">{t("Note", "备注")}: {k.note}</span>}
                      </div>
                    </td>
                  </tr>
                ),
                edit === k.id && (
                  <tr key={`${k.id}-e`} className="border-t">
                    <td colSpan={cols} className="p-0"><EditKey k={k} ownerRole={roleOf(k)} onSaved={() => { setEdit(null); onChanged(); }} /></td>
                  </tr>
                ),
              ];
            })}
          </tbody>
        </table>
      </div>
      {keys.length > live.length && (
        <button type="button" onClick={() => setShowOld(!showOld)} className="text-xs text-muted-foreground hover:text-foreground">
          {showOld ? t("Hide revoked keys", "隐藏已吊销的密钥") : t(`Show ${keys.length - live.length} revoked`, `显示 ${keys.length - live.length} 个已吊销`)}
        </button>
      )}
    </div>
  );
}
