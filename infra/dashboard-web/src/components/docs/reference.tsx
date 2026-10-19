"use client";

// API and MCP reference pages, rendered from docs/api/reference.json.

import * as React from "react";
import Link from "next/link";
import { Check, ChevronRight, Copy, KeyRound, Loader2, Lock, Play, ShieldCheck, Timer } from "lucide-react";

import { useLocale, useT } from "@/components/locale-provider";
import { useMe } from "@/components/user-menu";
import { DocMarkdown } from "@/components/docs/markdown";
import { Breadcrumbs, NavGroup, NavItem } from "@/components/docs/shell";
import { groupBy, type ApiEndpoint, type ApiField, type ApiReference, type ApiService, type McpTool } from "@/lib/docs";
import { cn } from "@/lib/utils";

// ── small pieces ─────────────────────────────────────────────────────────

const METHOD_CLS: Record<string, string> = {
  GET: "bg-emerald-500/10 text-emerald-700 ring-emerald-600/20",
  POST: "bg-blue-500/10 text-blue-700 ring-blue-600/20",
  PUT: "bg-amber-500/10 text-amber-700 ring-amber-600/20",
  PATCH: "bg-amber-500/10 text-amber-700 ring-amber-600/20",
  DELETE: "bg-red-500/10 text-red-700 ring-red-600/20",
};

export function Method({ m, small }: { m: string; small?: boolean }) {
  return (
    <span className={cn("inline-flex shrink-0 items-center justify-center rounded font-mono font-semibold ring-1 ring-inset",
      small ? "w-11 py-px text-[10px]" : "px-1.5 py-0.5 text-[11px]", METHOD_CLS[m] ?? "bg-muted text-foreground ring-border")}>
      {small && m === "DELETE" ? "DEL" : m}
    </span>
  );
}

function useCopy() {
  const [done, setDone] = React.useState(false);
  return { done, copy: (s: string) => navigator.clipboard.writeText(s).then(() => { setDone(true); setTimeout(() => setDone(false), 1400); }) };
}

function CopyIcon({ text, dark }: { text: string; dark?: boolean }) {
  const t = useT();
  const { done, copy } = useCopy();
  return (
    <button type="button" onClick={() => copy(text)} title={t("Copy", "复制")}
            className={cn("inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px]", dark ? "text-slate-400 hover:bg-white/10 hover:text-slate-100" : "text-muted-foreground hover:bg-accent")}>
      {done ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}

/** A dark, tabbed code panel. */
export function CodePanel({ tabs, title, className }: { tabs: { id: string; label: string; code: string }[]; title?: React.ReactNode; className?: string }) {
  const [cur, setCur] = React.useState(tabs[0]?.id);
  const active = tabs.find((x) => x.id === cur) ?? tabs[0];
  return (
    <div className={cn("code-panel overflow-hidden rounded-xl border border-slate-800 bg-[#0d1424] text-slate-100 shadow-sm", className)}>
      <div className="flex items-center gap-1 border-b border-white/10 bg-white/[0.03] px-2">
        {title && <span className="mr-2 px-1 text-[11px] font-medium uppercase tracking-wide text-slate-400">{title}</span>}
        {tabs.length > 1 && tabs.map((x) => (
          <button key={x.id} onClick={() => setCur(x.id)}
                  className={cn("-mb-px border-b-2 px-2 py-2 text-[12px] font-medium", x.id === active?.id ? "border-sky-400 text-white" : "border-transparent text-slate-400 hover:text-slate-200")}>
            {x.label}
          </button>
        ))}
        <span className="ml-auto">{active && <CopyIcon text={active.code} dark />}</span>
      </div>
      <pre className="max-h-[28rem] overflow-auto px-4 py-3 font-mono text-[12.5px] leading-relaxed"><code>{active?.code}</code></pre>
    </div>
  );
}

function Children({ f }: { f: ApiField }) {
  const t = useT();
  const [open, setOpen] = React.useState(false);
  if (!f.children?.length) return null;
  return (
    <div className="mt-2">
      <button type="button" onClick={() => setOpen(!open)}
              className="inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[12px] text-muted-foreground hover:bg-accent hover:text-foreground">
        <ChevronRight className={cn("h-3 w-3 transition-transform", open && "rotate-90")} />
        {open ? t("Hide child fields", "收起子字段") : t(`Show ${f.children.length} child fields`, `展开 ${f.children.length} 个子字段`)}
      </button>
      {open && <div className="mt-2"><FieldRows fields={f.children} nested /></div>}
    </div>
  );
}

function FieldRows({ fields, nested }: { fields: ApiField[]; nested?: boolean }) {
  const t = useT();
  if (!fields.length) return <p className="text-sm text-muted-foreground">{t("None.", "无。")}</p>;
  return (
    <div className={cn("divide-y rounded-lg border", nested && "bg-muted/25")}>
      {fields.map((f) => (
        <div key={`${f.in ?? ""}-${f.name}`} className="px-4 py-3">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <code className="font-mono text-[13.5px] font-semibold text-foreground">{f.name}</code>
            <span className="font-mono text-[12px] text-muted-foreground">{f.type}{f.nullable ? " | null" : ""}</span>
            {f.in && f.in !== "query" && <span className="rounded bg-muted px-1.5 text-[11px] text-muted-foreground">{f.in}</span>}
            {f.required ? <span className="text-[11px] font-semibold text-red-600">{t("required", "必填")}</span>
              : <span className="text-[11px] text-muted-foreground">{t("optional", "可选")}</span>}
          </div>
          {f.description && <p className="mt-1 whitespace-pre-line text-[13.5px] leading-relaxed text-foreground/80">{f.description}</p>}
          <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-muted-foreground">
            {f.default !== undefined && <span>{t("Default", "默认")}: <code className="font-mono text-foreground/80">{JSON.stringify(f.default)}</code></span>}
            {f.enum && <span>{t("One of", "可选值")}: {f.enum.map((v) => <code key={String(v)} className="mr-1 rounded bg-muted px-1 font-mono text-foreground/80">{String(v)}</code>)}</span>}
            {f.example !== undefined && <span>{t("Example", "示例")}: <code className="font-mono text-foreground/80">{typeof f.example === "string" ? f.example : JSON.stringify(f.example)}</code></span>}
            {f.range && <span>{t("Range", "范围")}: {f.range[0] ?? "−∞"} – {f.range[1] ?? "∞"}</span>}
          </div>
          <Children f={f} />
        </div>
      ))}
    </div>
  );
}

function H2({ id, children }: { id?: string; children: React.ReactNode }) {
  return <h2 id={id} className="mb-3 mt-10 scroll-mt-28 text-[17px] font-semibold tracking-tight">{children}</h2>;
}

// ── examples and code samples ────────────────────────────────────────────

const GUESS: [RegExp, unknown][] = [
  [/^tickers$/, "SPY,QQQ"], [/^ticker$|^symbol$|^underlying$/, "SPY"], [/^roots?$/, "CL"],
  [/start/, "2025-01-02"], [/end/, "2025-01-10"], [/date$/, "2025-01-02"], [/^as_of$/, "2025-01-10T20:00:00Z"],
  [/account_id/, "acc_1"], [/session_id/, "sess_1"], [/order_id/, "ord_1"], [/^limit$/, 100], [/^q$|query/, "earnings"],
];

export function exampleOf(f: ApiField, asList = false): unknown {
  if (f.example !== undefined && f.example !== null) return f.example;
  if (f.default !== undefined && f.default !== null) return f.default;
  if (f.enum?.length) return f.enum[0];
  const g = GUESS.find(([re]) => re.test(f.name));
  if (g) {
    if (asList && f.type.endsWith("[]") && typeof g[1] === "string") return String(g[1]).split(",");
    return g[1];
  }
  if (f.type.startsWith("integer") || f.type.startsWith("number")) return 1;
  if (f.type.startsWith("boolean")) return true;
  if (f.type.endsWith("[]")) return [];
  return "…";
}

function fillPath(path: string, values: Record<string, string>) {
  return path.replace(/\{(\w+)\}/g, (_, k) => values[k] || `{${k}}`);
}

function samples(svc: ApiService, ep: ApiEndpoint, values: Record<string, string>, body: string) {
  const path = fillPath(ep.path, values);
  const query = ep.params.filter((p) => p.in === "query" && values[p.name]);
  const url = `${svc.base}${path}`;
  const qs = new URLSearchParams(query.map((p) => [p.name, values[p.name]])).toString();
  const hasBody = ep.body && ["POST", "PUT", "PATCH"].includes(ep.method);
  let pretty = body;
  try { pretty = JSON.stringify(JSON.parse(body), null, 2); } catch { /* keep as typed */ }
  const curl = [`curl${ep.method !== "GET" ? ` -X ${ep.method}` : ""} "$QFZ_URL${url}${qs ? `?${qs}` : ""}" \\`,
    `  -H "Authorization: Bearer $QFZ_API_KEY"${hasBody ? " \\" : ""}`,
    ...(hasBody ? [`  -H "Content-Type: application/json" \\`, `  -d '${pretty.replace(/'/g, "'\\''")}'`] : [])].join("\n");
  const pyParams = query.length ? `,\n    params={${query.map((p) => `"${p.name}": ${JSON.stringify(values[p.name])}`).join(", ")}}` : "";
  const pyBody = hasBody ? `,\n    json=${pretty.replace(/\btrue\b/g, "True").replace(/\bfalse\b/g, "False").replace(/\bnull\b/g, "None").split("\n").join("\n    ")}` : "";
  const python = `import os, requests\n\nr = requests.${ep.method.toLowerCase()}(\n    os.environ["QFZ_URL"] + "${url}",\n    headers={"Authorization": f"Bearer {os.environ['QFZ_API_KEY']}"}${pyParams}${pyBody},\n)\nr.raise_for_status()\nprint(r.json())`;
  const js = `const res = await fetch(\`\${process.env.QFZ_URL}${url}${qs ? `?${qs}` : ""}\`, {\n${ep.method !== "GET" ? `  method: "${ep.method}",\n` : ""}  headers: {\n    Authorization: \`Bearer \${process.env.QFZ_API_KEY}\`,${hasBody ? `\n    "Content-Type": "application/json",` : ""}\n  },${hasBody ? `\n  body: JSON.stringify(${pretty.split("\n").join("\n  ")}),` : ""}\n});\nconsole.log(await res.json());`;
  return [{ id: "curl", label: "cURL", code: curl }, { id: "python", label: "Python", code: python }, { id: "js", label: "JavaScript", code: js }];
}

/** GET requests and ESP queries can be run from the page with the reader's session. */
function runnable(svc: ApiService, ep: ApiEndpoint) {
  return ep.method === "GET" || (svc.id === "esp" && ep.method === "POST");
}

function TryIt({ svc, ep, values, setValues, body, setBody }: {
  svc: ApiService; ep: ApiEndpoint; values: Record<string, string>; setValues: (v: Record<string, string>) => void;
  body: string; setBody: (b: string) => void;
}) {
  const t = useT();
  const { data: me } = useMe();
  const [busy, setBusy] = React.useState(false);
  const [res, setRes] = React.useState<{ status: number; ms: number; text: string } | null>(null);
  const send = async () => {
    setBusy(true);
    const path = fillPath(ep.path, values);
    const qs = new URLSearchParams(ep.params.filter((p) => p.in === "query" && values[p.name]).map((p) => [p.name, values[p.name]])).toString();
    const t0 = performance.now();
    try {
      const r = await fetch(`${svc.base}${path}${qs ? `?${qs}` : ""}`, {
        method: ep.method, credentials: "same-origin",
        headers: ep.body ? { "content-type": "application/json" } : {},
        body: ep.method !== "GET" && ep.body ? body : undefined,
      });
      let text = await r.text();
      try { text = JSON.stringify(JSON.parse(text), null, 2); } catch { /* not JSON */ }
      setRes({ status: r.status, ms: Math.round(performance.now() - t0), text: text.length > 60_000 ? text.slice(0, 60_000) + "\n…" : text });
    } catch (e) {
      setRes({ status: 0, ms: 0, text: String(e) });
    } finally {
      setBusy(false);
    }
  };
  const inputs = ep.params.filter((p) => p.in === "query" || p.in === "path");
  return (
    <div className="rounded-xl border bg-card">
      <div className="flex items-center justify-between border-b px-4 py-2.5">
        <span className="flex items-center gap-2 text-sm font-semibold"><Play className="h-3.5 w-3.5 text-primary" />{t("Try it", "在线调用")}</span>
        {!me && <span className="flex items-center gap-1 text-xs text-muted-foreground"><Lock className="h-3 w-3" />{t("Sign in to send requests", "登录后可发送请求")}</span>}
      </div>
      <div className="space-y-2.5 p-4">
        {inputs.map((p) => (
          <label key={p.name} className="grid grid-cols-[9rem_1fr] items-center gap-3 text-[13px]">
            <span className="truncate font-mono">{p.name}{p.required && <span className="text-red-600">*</span>}</span>
            {p.enum ? (
              <select className="h-8 rounded-md border bg-background px-2 font-mono text-[12.5px]" value={values[p.name] ?? ""}
                      onChange={(e) => setValues({ ...values, [p.name]: e.target.value })}>
                <option value="">—</option>
                {p.enum.map((v) => <option key={String(v)} value={String(v)}>{String(v)}</option>)}
              </select>
            ) : (
              <input className="h-8 rounded-md border bg-background px-2 font-mono text-[12.5px] outline-none focus:border-ring" value={values[p.name] ?? ""}
                     placeholder={p.type} onChange={(e) => setValues({ ...values, [p.name]: e.target.value })} />
            )}
          </label>
        ))}
        {ep.body && ep.method !== "GET" && (
          <textarea className="h-36 w-full rounded-md border bg-background p-2 font-mono text-[12.5px] outline-none focus:border-ring" value={body}
                    onChange={(e) => setBody(e.target.value)} spellCheck={false} />
        )}
        <button onClick={send} disabled={busy || !me}
                className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-[13px] font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />} {t("Send request", "发送请求")}
        </button>
      </div>
      {res && (
        <div className="border-t">
          <div className="flex items-center gap-3 px-4 py-2 text-xs">
            <span className={cn("rounded px-1.5 py-0.5 font-mono font-semibold", res.status >= 200 && res.status < 300 ? "bg-emerald-500/10 text-emerald-700" : "bg-red-500/10 text-red-700")}>{res.status || "ERR"}</span>
            <span className="flex items-center gap-1 text-muted-foreground"><Timer className="h-3 w-3" />{res.ms} ms</span>
            <span className="text-muted-foreground">{(res.text.length / 1024).toFixed(1)} KB</span>
          </div>
          <pre className="max-h-80 overflow-auto border-t bg-muted/40 px-4 py-3 font-mono text-[12px] leading-relaxed">{res.text}</pre>
        </div>
      )}
    </div>
  );
}

// ── navigation ───────────────────────────────────────────────────────────

export function ApiNav({ ref_, service, endpoint }: { ref_?: ApiReference; service?: string; endpoint?: string }) {
  const t = useT();
  const { locale } = useLocale();
  return (
    <nav aria-label={t("API reference", "API 参考")}>
      <ul className="mb-4 space-y-px">
        <NavItem href="/docs/api" active={!service}>{t("Overview and authentication", "概览与认证")}</NavItem>
      </ul>
      {(ref_?.services ?? []).map((s) => (
        <NavGroup key={s.id} title={locale === "zh" ? s.title.zh : s.title.en} active={s.id === service} defaultOpen={s.id === service}>
          <NavItem href={`/docs/api/${s.id}`} active={s.id === service && !endpoint}>{t("Overview", "概览")}</NavItem>
          {groupBy(s.endpoints, (e) => e.group).map(([g, eps]) => (
            <React.Fragment key={g}>
              <li className="px-2 pb-0.5 pt-2.5 text-[11.5px] font-medium text-muted-foreground/80">{g}</li>
              {eps.map((e) => (
                <NavItem key={e.id} href={`/docs/api/${s.id}/${e.id}`} active={s.id === service && e.id === endpoint}>
                  <Method m={e.method} small />
                  <span className="truncate">{e.summary}</span>
                </NavItem>
              ))}
            </React.Fragment>
          ))}
        </NavGroup>
      ))}
    </nav>
  );
}

export function McpNav({ ref_, tool }: { ref_?: ApiReference; tool?: string }) {
  const t = useT();
  return (
    <nav aria-label={t("MCP tools", "MCP 工具")}>
      <ul className="mb-4 space-y-px">
        <NavItem href="/docs/mcp" active={!tool}>{t("Connect an agent", "接入 agent")}</NavItem>
      </ul>
      {groupBy(ref_?.mcp ?? [], (x) => x.group).map(([g, tools]) => (
        <NavGroup key={g} title={g} active={tools.some((x) => x.name === tool)} defaultOpen>
          {tools.map((x) => <NavItem key={x.name} href={`/docs/mcp/${x.name}`} active={x.name === tool} mono>{x.name}</NavItem>)}
        </NavGroup>
      ))}
    </nav>
  );
}

// ── pages ────────────────────────────────────────────────────────────────

const ERRORS: [string, string, string][] = [
  ["400", "Invalid parameters; the body says which.", "参数无效；响应体会说明原因。"],
  ["401", "No key, or the key is invalid, revoked or expired.", "缺少 key，或 key 无效、已吊销、已过期。"],
  ["403", "The key's role or scopes do not allow this request, or the key is read-only.", "key 的角色或 scope 不允许该请求，或 key 为只读。"],
  ["404", "Unknown resource, or one that belongs to another user.", "资源不存在，或属于其他用户。"],
  ["429", "The key's rate limit was reached; wait Retry-After seconds.", "达到 key 的速率限制；等待 Retry-After 秒后重试。"],
  ["502", "The service behind the hub is not running.", "hub 后面的服务没有运行。"],
];

const SCOPES: [string, string, string][] = [
  ["market-data", "UPQ", "viewer"], ["events", "ESP", "viewer"], ["trading", "PMB", "researcher"],
  ["mcp", "/mcp", "researcher"], ["chat", "chat", "researcher"], ["admin", "data admin, users", "admin"],
];

export function ApiHome({ ref_ }: { ref_?: ApiReference }) {
  const t = useT();
  const { locale } = useLocale();
  const [origin, setOrigin] = React.useState("https://your-host");
  React.useEffect(() => setOrigin(window.location.origin), []);
  return (
    <div>
      <Breadcrumbs items={[{ label: t("API reference", "API 参考") }]} />
      <h1 className="text-[2rem] font-semibold tracking-tight">{t("API reference", "API 参考")}</h1>
      <p className="mt-3 text-[16px] leading-relaxed text-muted-foreground">
        {t("Every service is reached through the hub with one API key. Market data and events are read-only queries; the paper broker keeps state per user.",
          "所有服务都通过 hub 访问，使用同一把 API key。行情与事件是只读查询；模拟券商按用户保存状态。")}
      </p>
      <div className="mt-8 grid gap-3 sm:grid-cols-2">
        {(ref_?.services ?? []).map((s) => (
          <Link key={s.id} href={`/docs/api/${s.id}`} className="group rounded-xl border p-4 transition-colors hover:border-primary/40 hover:bg-primary/[0.02]">
            <div className="flex items-center justify-between">
              <span className="font-semibold">{locale === "zh" ? s.title.zh : s.title.en}</span>
              <ChevronRight className="h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
            </div>
            <p className="mt-1 text-[13px] text-muted-foreground">{locale === "zh" ? s.summary.zh : s.summary.en}</p>
            <p className="mt-3 flex items-center gap-3 text-[12px] text-muted-foreground">
              <code className="font-mono">{s.base}</code><span>{t(`${s.endpoints.length} endpoints`, `${s.endpoints.length} 个接口`)}</span>
            </p>
          </Link>
        ))}
        <Link href="/docs/mcp" className="group rounded-xl border p-4 transition-colors hover:border-primary/40 hover:bg-primary/[0.02]">
          <div className="flex items-center justify-between">
            <span className="font-semibold">{t("MCP tools", "MCP 工具")}</span>
            <ChevronRight className="h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
          </div>
          <p className="mt-1 text-[13px] text-muted-foreground">{t("The same services as tools for agents, with a time lock to a simulation.", "同样的服务以工具形式提供给 agent，并可时间锁定到模拟会话。")}</p>
          <p className="mt-3 flex items-center gap-3 text-[12px] text-muted-foreground"><code className="font-mono">/mcp</code><span>{t(`${ref_?.mcp.length ?? 0} tools`, `${ref_?.mcp.length ?? 0} 个工具`)}</span></p>
        </Link>
      </div>

      <H2 id="authentication">{t("Authentication", "认证")}</H2>
      <p className="text-[15px] leading-relaxed text-foreground/85">
        {t("Create a key on your ", "在你的")}<Link href="/account" className="font-medium text-primary hover:underline">{t("account page", "账号页")}</Link>
        {t(" (or ask an admin to issue one) and send it as a bearer token. ", "创建 key（或请管理员发放），以 bearer token 发送。")}
        <code className="rounded bg-muted px-1 font-mono text-[13px]">X-API-Key</code>{t(" works too. Keep the token out of URLs and source control.", " 也可以。不要把 token 放进 URL 或代码仓库。")}
      </p>
      <CodePanel className="mt-4" tabs={[
        { id: "env", label: t("Environment", "环境变量"), code: `export QFZ_URL=${origin}\nexport QFZ_API_KEY=qfz_…` },
        { id: "curl", label: "cURL", code: `curl "$QFZ_URL/svc/upq/health" \\\n  -H "Authorization: Bearer $QFZ_API_KEY"` },
      ]} />
      <H2 id="scopes">{t("Scopes", "Scope")}</H2>
      <p className="mb-3 text-[15px] text-foreground/85">{t("A key can be limited to some services, read-only, an expiry and a rate limit. It never exceeds its owner's role.", "key 可以限定服务范围、只读、到期日和速率，权限永远不超过所有者的角色。")} <Link href="/docs/platform-guide#handing-out-api-keys" className="font-medium text-primary hover:underline">{t("More", "详情")}</Link></p>
      <div className="overflow-hidden rounded-lg border text-[13.5px]">
        <table className="w-full">
          <thead className="bg-muted/60 text-left text-[12px] text-muted-foreground"><tr><th className="px-4 py-2">scope</th><th className="px-4 py-2">{t("Reaches", "可访问")}</th><th className="px-4 py-2">{t("Least owner role", "所有者最低角色")}</th></tr></thead>
          <tbody>{SCOPES.map(([s, r, role]) => <tr key={s} className="border-t"><td className="px-4 py-2 font-mono">{s}</td><td className="px-4 py-2">{r}</td><td className="px-4 py-2 text-muted-foreground">{role}</td></tr>)}</tbody>
        </table>
      </div>
      <H2 id="errors">{t("Errors", "错误")}</H2>
      <div className="divide-y rounded-lg border">
        {ERRORS.map(([code, en, zh]) => (
          <div key={code} className="flex gap-4 px-4 py-2.5 text-[13.5px]">
            <code className={cn("w-10 shrink-0 font-mono font-semibold", code.startsWith("4") ? "text-amber-700" : "text-red-700")}>{code}</code>
            <span className="text-foreground/85">{t(en, zh)}</span>
          </div>
        ))}
      </div>
      <p className="mt-3 text-[13.5px] text-muted-foreground">{t("Errors are JSON: the hub answers {\"error\": …, \"status\": …}; services answer {\"detail\": …} or {\"code\": …, \"message\": …}.", "错误都是 JSON：hub 返回 {\"error\": …, \"status\": …}；各服务返回 {\"detail\": …} 或 {\"code\": …, \"message\": …}。")}</p>
      <H2 id="time-lock">{t("Point in time", "时点控制")}</H2>
      <p className="text-[15px] leading-relaxed text-foreground/85">
        {t("Market data takes an as_of cap and events are returned as known at a time, so a replay never reads the future. MCP tools can be locked to a simulation session with the X-QFZ-Session header.",
          "行情接口接受 as_of 上限，事件按某一时刻已知的内容返回，回放时不会读到未来数据。MCP 工具可以用 X-QFZ-Session header 锁定到某个模拟会话。")} <Link href="/docs/platform-guide#1-time-lock" className="font-medium text-primary hover:underline">{t("Time lock", "时间锁")}</Link>
      </p>
    </div>
  );
}

export function ServicePage({ svc }: { svc: ApiService }) {
  const t = useT();
  const { locale } = useLocale();
  const title = locale === "zh" ? svc.title.zh : svc.title.en;
  return (
    <div>
      <Breadcrumbs items={[{ label: t("API reference", "API 参考"), href: "/docs/api" }, { label: title }]} />
      <h1 className="text-[2rem] font-semibold tracking-tight">{title}</h1>
      <p className="mt-3 text-[16px] leading-relaxed text-muted-foreground">{locale === "zh" ? svc.summary.zh : svc.summary.en}</p>
      <div className="mt-6 flex flex-wrap gap-3 text-[13px]">
        <span className="inline-flex items-center gap-2 rounded-lg border px-3 py-1.5"><span className="text-muted-foreground">{t("Base path", "基础路径")}</span><code className="font-mono">{svc.base}</code><CopyIcon text={svc.base} /></span>
        <span className="inline-flex items-center gap-2 rounded-lg border px-3 py-1.5"><ShieldCheck className="h-3.5 w-3.5 text-muted-foreground" /><span className="text-muted-foreground">scope</span><code className="font-mono">{svc.scope}</code></span>
        {svc.version && <span className="inline-flex items-center gap-2 rounded-lg border px-3 py-1.5"><span className="text-muted-foreground">{t("Version", "版本")}</span><code className="font-mono">{svc.version}</code></span>}
      </div>
      {svc.intro && <div className="mt-6"><DocMarkdown>{svc.intro.replace(/^#+\s.*\n/, "")}</DocMarkdown></div>}
      {groupBy(svc.endpoints, (e) => e.group).map(([g, eps]) => (
        <section key={g}>
          <H2>{g}</H2>
          <div className="divide-y overflow-hidden rounded-lg border">
            {eps.map((e) => (
              <Link key={e.id} href={`/docs/api/${svc.id}/${e.id}`} className="group flex items-center gap-3 px-4 py-2.5 hover:bg-accent/50">
                <Method m={e.method} small />
                <code className="min-w-0 shrink-0 font-mono text-[13px]">{e.path}</code>
                <span className="ml-auto truncate text-right text-[13px] text-muted-foreground">{e.summary}</span>
                <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 group-hover:opacity-100" />
              </Link>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

export function EndpointPage({ svc, ep }: { svc: ApiService; ep: ApiEndpoint }) {
  const t = useT();
  const { locale } = useLocale();
  const init = React.useMemo(() => Object.fromEntries(ep.params.filter((p) => p.required || p.in === "path")
    .map((p) => [p.name, String(exampleOf(p))])), [ep]);
  const [values, setValues] = React.useState<Record<string, string>>(init);
  const [body, setBody] = React.useState(() => JSON.stringify(ep.body?.example ?? {}, null, 2));
  React.useEffect(() => { setValues(init); setBody(JSON.stringify(ep.body?.example ?? {}, null, 2)); }, [ep, init]);
  const fullPath = `${svc.base}${ep.path}`;
  const ok = ep.responses.find((r) => r.status.startsWith("2") && r.example !== undefined);
  const query = ep.params.filter((p) => p.in === "query");
  const path = ep.params.filter((p) => p.in === "path");
  const header = ep.params.filter((p) => p.in === "header");
  return (
    <div className="grid gap-10 2xl:grid-cols-[minmax(0,1fr)_30rem] xl:grid-cols-[minmax(0,1fr)_26rem]">
      <div className="min-w-0">
        <Breadcrumbs items={[{ label: t("API reference", "API 参考"), href: "/docs/api" },
          { label: locale === "zh" ? svc.title.zh : svc.title.en, href: `/docs/api/${svc.id}` }, { label: ep.group }]} />
        <h1 className="text-[1.75rem] font-semibold tracking-tight">{ep.summary}</h1>
        <div className="mt-4 flex items-center gap-2 rounded-lg border bg-muted/30 px-3 py-2">
          <Method m={ep.method} />
          <code className="min-w-0 flex-1 truncate font-mono text-[13.5px]">{fullPath}</code>
          <CopyIcon text={fullPath} />
        </div>
        <div className="mt-3 flex flex-wrap gap-2 text-[12px] text-muted-foreground">
          <span className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5"><KeyRound className="h-3 w-3" />{t("API key", "API key")}</span>
          <span className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5"><ShieldCheck className="h-3 w-3" />scope <code className="font-mono">{svc.scope}</code></span>
          {ep.deprecated && <span className="rounded-full border border-amber-500/40 px-2 py-0.5 text-amber-700">{t("deprecated", "已弃用")}</span>}
        </div>
        {ep.description && <div className="mt-6"><DocMarkdown>{ep.description}</DocMarkdown></div>}
        {path.length > 0 && <><H2 id="path">{t("Path parameters", "路径参数")}</H2><FieldRows fields={path} /></>}
        {query.length > 0 && <><H2 id="query">{t("Query parameters", "查询参数")}</H2><FieldRows fields={query} /></>}
        {header.length > 0 && <><H2 id="headers">{t("Headers", "请求头")}</H2><FieldRows fields={header} /></>}
        {ep.body && <><H2 id="body">{t("Request body", "请求体")} <span className="ml-1 font-mono text-[12px] font-normal text-muted-foreground">application/json</span></H2><FieldRows fields={ep.body.fields} /></>}
        {!path.length && !query.length && !ep.body && <><H2>{t("Parameters", "参数")}</H2><p className="text-sm text-muted-foreground">{t("This endpoint takes no parameters.", "此接口没有参数。")}</p></>}
        <H2 id="responses">{t("Responses", "响应")}</H2>
        <div className="divide-y rounded-lg border">
          {ep.responses.map((r) => (
            <div key={r.status} className="flex gap-4 px-4 py-2.5 text-[13.5px]">
              <code className={cn("w-10 shrink-0 font-mono font-semibold", r.status.startsWith("2") ? "text-emerald-700" : "text-amber-700")}>{r.status}</code>
              <span className="text-foreground/85">{r.description || "—"}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="min-w-0">
        <div className="space-y-4 xl:sticky" style={{ top: "calc(var(--nav-h, 48px) + var(--docs-bar) + 2rem)" }}>
          <CodePanel title={t("Request", "请求")} tabs={samples(svc, ep, values, body)} />
          {ok && <CodePanel title={`${t("Response", "响应")} ${ok.status}`} tabs={[{ id: "json", label: "JSON", code: JSON.stringify(ok.example, null, 2) }]} />}
          {runnable(svc, ep) && <TryIt svc={svc} ep={ep} values={values} setValues={setValues} body={body} setBody={setBody} />}
        </div>
      </div>
    </div>
  );
}

function mcpConfig(origin: string) {
  return JSON.stringify({ mcpServers: { qfinzero: { type: "http", url: `${origin}/mcp/`, headers: { Authorization: "Bearer qfz_…" } } } }, null, 2);
}

export function McpHome({ ref_ }: { ref_?: ApiReference }) {
  const t = useT();
  const [origin, setOrigin] = React.useState("https://your-host");
  React.useEffect(() => setOrigin(window.location.origin), []);
  return (
    <div>
      <Breadcrumbs items={[{ label: t("MCP tools", "MCP 工具") }]} />
      <h1 className="text-[2rem] font-semibold tracking-tight">{t("Connect an agent over MCP", "通过 MCP 接入 agent")}</h1>
      <p className="mt-3 text-[16px] leading-relaxed text-muted-foreground">
        {t(`The hub serves ${ref_?.mcp.length ?? ""} tools at /mcp over streamable HTTP: market data, events, research and the paper broker. A key with the mcp scope reaches the tools its other scopes allow.`,
          `hub 在 /mcp 以 streamable HTTP 提供 ${ref_?.mcp.length ?? ""} 个工具：行情、事件、研究和模拟券商。带 mcp scope 的 key 能调用其他 scope 允许的工具。`)}
      </p>
      <H2 id="config">{t("Client configuration", "客户端配置")}</H2>
      <CodePanel tabs={[
        { id: "json", label: t("JSON (Claude, Cursor…)", "JSON（Claude、Cursor…）"), code: mcpConfig(origin) },
        { id: "claude", label: "Claude Code", code: `claude mcp add --transport http qfinzero ${origin}/mcp/ \\\n  --header "Authorization: Bearer $QFZ_API_KEY"` },
        { id: "python", label: "Python", code: `import asyncio, os\nfrom mcp import ClientSession\nfrom mcp.client.streamable_http import streamablehttp_client\n\nasync def main():\n    headers = {"Authorization": f"Bearer {os.environ['QFZ_API_KEY']}"}\n    async with streamablehttp_client(os.environ["QFZ_URL"] + "/mcp/", headers=headers) as (read, write, _):\n        async with ClientSession(read, write) as session:\n            await session.initialize()\n            tools = await session.list_tools()\n            print([t.name for t in tools.tools])\n\nasyncio.run(main())` },
      ]} />
      <div className="callout mt-5 flex gap-3 rounded-lg border border-primary/30 bg-primary/[0.05] px-4 py-3 text-[14px]">
        <Timer className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <p>{t("Add the header X-QFZ-Session: sess_… to lock every data tool to a simulation session's clock, so the agent cannot read past the current bar.", "加上 X-QFZ-Session: sess_… header，可以把所有数据工具锁定到模拟会话的时钟，agent 读不到当前 bar 之后的数据。")}</p>
      </div>
      {groupBy(ref_?.mcp ?? [], (x) => x.group).map(([g, tools]) => (
        <section key={g}>
          <H2>{g}</H2>
          <div className="divide-y overflow-hidden rounded-lg border">
            {tools.map((x) => (
              <Link key={x.name} href={`/docs/mcp/${x.name}`} className="group flex items-baseline gap-4 px-4 py-2.5 hover:bg-accent/50">
                <code className="w-52 shrink-0 font-mono text-[13px] font-medium">{x.name}</code>
                <span className="min-w-0 flex-1 truncate text-[13px] text-muted-foreground">{x.summary}</span>
              </Link>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

const TOOL_SCOPE: [string, string][] = [["upq_", "market-data"], ["research_", "market-data"], ["esp_", "events"], ["pmb_", "trading"]];

export function ToolPage({ tool }: { tool: McpTool }) {
  const t = useT();
  const args: Record<string, unknown> = Object.fromEntries(tool.params.filter((p) => p.required).map((p) => [p.name, exampleOf(p, true)]));
  if (tool.name.includes("future") && "symbol" in args && !tool.params.find((p) => p.name === "symbol")?.example) args.symbol = "CL";
  const scope = TOOL_SCOPE.find(([p]) => tool.name.startsWith(p))?.[1];
  const argsJson = JSON.stringify(args, null, 2);
  return (
    <div className="grid gap-10 xl:grid-cols-[minmax(0,1fr)_26rem] 2xl:grid-cols-[minmax(0,1fr)_30rem]">
      <div className="min-w-0">
        <Breadcrumbs items={[{ label: t("MCP tools", "MCP 工具"), href: "/docs/mcp" }, { label: tool.group }]} />
        <h1 className="font-mono text-[1.6rem] font-semibold tracking-tight">{tool.name}</h1>
        <p className="mt-3 text-[16px] leading-relaxed text-foreground/85">{tool.summary}</p>
        <div className="mt-3 flex flex-wrap gap-2 text-[12px] text-muted-foreground">
          <span className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5"><ShieldCheck className="h-3 w-3" />scope <code className="font-mono">mcp</code>{scope && <> + <code className="font-mono">{scope}</code></>}</span>
        </div>
        {tool.description && <div className="mt-6"><DocMarkdown>{tool.description}</DocMarkdown></div>}
        <H2 id="arguments">{t("Arguments", "参数")}</H2>
        <FieldRows fields={tool.params} />
        {tool.returns && <><H2 id="returns">{t("Returns", "返回")}</H2><p className="text-[14.5px] leading-relaxed text-foreground/85">{tool.returns}</p></>}
      </div>
      <div className="min-w-0">
        <div className="space-y-4 xl:sticky" style={{ top: "calc(var(--nav-h, 48px) + var(--docs-bar) + 2rem)" }}>
          <CodePanel title={t("Call", "调用")} tabs={[
            { id: "rpc", label: "JSON-RPC", code: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: tool.name, arguments: args } }, null, 2) },
            { id: "python", label: "Python", code: `result = await session.call_tool(\n    "${tool.name}",\n    ${argsJson.split("\n").join("\n    ")},\n)\nprint(result.content[0].text)` },
          ]} />
        </div>
      </div>
    </div>
  );
}
