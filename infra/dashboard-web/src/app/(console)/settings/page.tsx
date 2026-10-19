"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Check, Download, Eye, EyeOff, FileUp, Loader2, Plus, RefreshCw, Search, Trash2, Upload, X,
} from "lucide-react";

import { useLocale, useT } from "@/components/locale-provider";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import {
  API_META, API_TYPES, emptySettings, exportJson, loadSettings, mergeImport, newId, parseImport, saveSettings,
  type ApiType, type Imported, type ModelGroup, type ModelSettings,
} from "@/lib/model-groups";
import { cn } from "@/lib/utils";
import { NewsPanel } from "@/components/settings/news-panel";
import { RatesPanel } from "@/components/settings/rates-panel";
import { useMe } from "@/components/user-menu";

const inputCls =
  "w-full rounded-md border border-input bg-card px-3 py-1.5 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/20";

type FetchState = { status: "idle" | "loading" | "ok" | "error"; error?: string };

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-foreground/20 p-4 pt-[10vh]" onClick={onClose}>
      <div className="w-full max-w-xl rounded-lg border bg-card" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={title}>
        <div className="flex items-center justify-between border-b px-4 py-3">
          <h2 className="text-[15px] font-semibold">{title}</h2>
          <button onClick={onClose} className="rounded-md p-1 text-muted-foreground hover:bg-accent" aria-label="close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="space-y-3 p-4">{children}</div>
      </div>
    </div>
  );
}

function GroupCard({
  group, active, fetchState, onChange, onRemove, onFetch, onSelect,
}: {
  group: ModelGroup;
  active: string | null;
  fetchState: FetchState;
  onChange: (patch: Partial<ModelGroup>) => void;
  onRemove: () => void;
  onFetch: () => void;
  onSelect: (model: string) => void;
}) {
  const t = useT();
  const { locale } = useLocale();
  const [showKey, setShowKey] = useState(false);
  const [q, setQ] = useState("");
  const [all, setAll] = useState(false);
  const meta = API_META[group.api];
  const models = group.models.filter((m) => !q || `${m.id} ${m.name}`.toLowerCase().includes(q.toLowerCase()));
  const shown = all ? models : models.slice(0, 40);

  return (
    <Card>
      <CardHeader className="flex-row items-center gap-3 space-y-0">
        <input
          value={group.name}
          onChange={(e) => onChange({ name: e.target.value })}
          className="min-w-0 flex-1 rounded-md bg-transparent px-1 py-0.5 text-[15px] font-semibold outline-none hover:bg-muted/60 focus:bg-muted/60"
          aria-label={t("Group name", "分组名称")}
        />
        <Badge variant="secondary">{meta.label}</Badge>
        {active && <Badge variant="success"><Check className="h-3 w-3" /> {t("in use", "使用中")}</Badge>}
        <button onClick={onRemove} className="rounded-md p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive" title={t("Delete group", "删除分组")}>
          <Trash2 className="h-4 w-4" />
        </button>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 md:grid-cols-[180px_1fr_1fr]">
          <label className="space-y-1">
            <span className="text-xs text-muted-foreground">{t("API type", "接口类型")}</span>
            <select className={inputCls} value={group.api} onChange={(e) => onChange({ api: e.target.value as ApiType })}>
              {API_TYPES.map((a) => (
                <option key={a} value={a}>{API_META[a].label}</option>
              ))}
            </select>
          </label>
          <label className="space-y-1">
            <span className="text-xs text-muted-foreground">Base URL</span>
            <input className={cn(inputCls, "font-mono text-[13px]")} value={group.baseUrl} placeholder={meta.base || "http://host:8081/antigravity"}
              onChange={(e) => onChange({ baseUrl: e.target.value.trim() })} />
          </label>
          <label className="space-y-1">
            <span className="text-xs text-muted-foreground">{t("API key", "API 密钥")}</span>
            <div className="relative">
              <input className={cn(inputCls, "pr-9 font-mono text-[13px]")} type={showKey ? "text" : "password"} value={group.apiKey}
                placeholder="sk-…" autoComplete="off" onChange={(e) => onChange({ apiKey: e.target.value.trim() })} />
              <button type="button" onClick={() => setShowKey((v) => !v)} className="absolute right-2 top-1.5 text-muted-foreground hover:text-foreground"
                title={showKey ? t("Hide", "隐藏") : t("Show", "显示")}>
                {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </label>
        </div>
        <p className="text-xs text-muted-foreground">{locale === "zh" ? meta.hint[1] : meta.hint[0]}</p>

        <div className="flex flex-wrap items-center gap-2 border-t pt-3">
          <Button size="sm" variant="outline" onClick={onFetch} disabled={!group.baseUrl || fetchState.status === "loading"}>
            {fetchState.status === "loading" ? <Loader2 className="animate-spin" /> : <RefreshCw />}
            {t("Fetch models", "获取模型列表")}
          </Button>
          <span className="text-xs text-muted-foreground">
            {group.models.length
              ? t(`${group.models.length} models`, `${group.models.length} 个模型`) +
                (group.fetchedAt ? t(` · fetched ${new Date(group.fetchedAt).toLocaleString()}`, ` · 获取于 ${new Date(group.fetchedAt).toLocaleString()}`) : "")
              : t("No models yet: fetch them from /models", "还没有模型：从 /models 获取")}
          </span>
          {group.models.length > 8 && (
            <label className="relative ml-auto">
              <Search className="pointer-events-none absolute left-2 top-2 h-3.5 w-3.5 text-muted-foreground" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("Filter models", "筛选模型")}
                className="w-48 rounded-md border border-input bg-card py-1 pl-7 pr-2 text-[13px] outline-none focus:border-ring" />
            </label>
          )}
        </div>
        {fetchState.status === "error" && <Alert variant="error" title={t("Could not fetch models", "获取模型失败")}>{fetchState.error}</Alert>}

        {shown.length > 0 && (
          <div className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {shown.map((m) => {
              const on = active === m.id;
              return (
                <button key={m.id} onClick={() => onSelect(m.id)} title={t("Use this model in Chat", "在对话中使用此模型")}
                  className={cn("flex min-w-0 items-center gap-2 rounded-md border px-2.5 py-1.5 text-left transition-colors",
                    on ? "border-primary bg-primary/5" : "hover:border-primary/40 hover:bg-muted/40")}>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-mono text-[12.5px]">{m.id}</span>
                    {m.name !== m.id && <span className="block truncate text-[11px] text-muted-foreground">{m.name}</span>}
                  </span>
                  {on && <Check className="h-3.5 w-3.5 shrink-0 text-primary" />}
                </button>
              );
            })}
          </div>
        )}
        {models.length > shown.length && (
          <button onClick={() => setAll(true)} className="text-xs font-medium text-primary hover:underline">
            {t(`Show all ${models.length}`, `显示全部 ${models.length} 个`)}
          </button>
        )}
      </CardContent>
    </Card>
  );
}

export default function SettingsPage() {
  const { data: me } = useMe();
  const t = useT();
  const [s, setS] = useState<ModelSettings>(emptySettings());
  const [loaded, setLoaded] = useState(false);
  const [fetchState, setFetchState] = useState<Record<string, FetchState>>({});
  const [proxyLoaded, setProxyLoaded] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);

  useEffect(() => {
    const current = loadSettings();
    fetch("/api/providers/env-keys")
      .then((r) => r.json())
      .then((d: { keys?: Record<string, string>; proxyLoaded?: boolean }) => {
        setProxyLoaded(Boolean(d.proxyLoaded));
        // first visit: offer the keys configured on the server as groups
        if (!current.groups.length) {
          const seeded: ModelGroup[] = [];
          if (d.keys?.openai) seeded.push({ id: newId(), name: "OpenAI", api: "openai", baseUrl: API_META.openai.base, apiKey: d.keys.openai, models: [] });
          if (d.keys?.claude) seeded.push({ id: newId(), name: "Claude", api: "anthropic", baseUrl: API_META.anthropic.base, apiKey: d.keys.claude, models: [] });
          if (seeded.length) current.groups = seeded;
        }
        setS(current);
      })
      .catch(() => setS(current))
      .finally(() => setLoaded(true));
  }, []);

  function commit(next: ModelSettings) {
    setS(next);
    saveSettings(next);
  }

  const update = (id: string, patch: Partial<ModelGroup>) =>
    commit({ ...s, groups: s.groups.map((g) => (g.id === id ? { ...g, ...patch } : g)) });

  function addGroup(api: ApiType) {
    const g: ModelGroup = { id: newId(), name: API_META[api].label, api, baseUrl: API_META[api].base, apiKey: "", models: [] };
    commit({ ...s, groups: [...s.groups, g] });
  }

  function removeGroup(g: ModelGroup) {
    if (!window.confirm(t(`Delete the group "${g.name}"?`, `删除分组「${g.name}」？`))) return;
    commit({ ...s, groups: s.groups.filter((x) => x.id !== g.id), active: s.active?.groupId === g.id ? null : s.active });
  }

  async function fetchModels(g: ModelGroup) {
    setFetchState((f) => ({ ...f, [g.id]: { status: "loading" } }));
    try {
      const res = await fetch("/api/playground/models", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ api: g.api, base_url: g.baseUrl, api_key: g.apiKey, proxy: s.proxy || undefined }),
      });
      const d = (await res.json()) as { ok: boolean; models?: { id: string; name: string }[]; error?: string };
      if (!d.ok) throw new Error(d.error ?? `HTTP ${res.status}`);
      const latest = loadSettings();
      commit({ ...latest, groups: latest.groups.map((x) => (x.id === g.id ? { ...x, models: d.models ?? [], fetchedAt: new Date().toISOString() } : x)) });
      setFetchState((f) => ({ ...f, [g.id]: { status: "ok" } }));
    } catch (e) {
      setFetchState((f) => ({ ...f, [g.id]: { status: "error", error: (e as Error).message } }));
    }
  }

  const activeGroup = s.groups.find((g) => g.id === s.active?.groupId);

  return (
    <div className="space-y-5">
      <PageHeader
        title={t("Settings", "设置")}
        description={t(
          "Model groups used by Chat. Keys are stored only in this browser.",
          "对话使用的模型分组。密钥只保存在当前浏览器中。",
        )}
        actions={
          <>
            <Button size="sm" variant="outline" onClick={() => setImportOpen(true)}><Upload /> {t("Import", "导入")}</Button>
            <Button size="sm" variant="outline" onClick={() => setExportOpen(true)} disabled={!s.groups.length}><Download /> {t("Export", "导出")}</Button>
          </>
        }
      />

      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 p-4">
          <span className="text-sm text-muted-foreground">{t("Chat uses", "对话当前使用")}</span>
          {activeGroup && s.active ? (
            <>
              <span className="font-mono text-sm font-medium">{s.active.model}</span>
              <Badge variant="secondary">{activeGroup.name}</Badge>
            </>
          ) : (
            <span className="text-sm text-warning">{t("no model selected: fetch a group's models and pick one", "未选择模型：获取某个分组的模型后点选一个")}</span>
          )}
        </CardContent>
      </Card>

      {loaded && !s.groups.length && (
        <Alert variant="info" title={t("No model groups yet", "还没有模型分组")}>
          {t("Add a group below, or import a Claude Code settings.json, export lines or a Codex config.toml.",
             "在下方添加分组，或导入 Claude Code 的 settings.json、export 环境变量或 Codex 的 config.toml。")}
        </Alert>
      )}

      {s.groups.map((g) => (
        <GroupCard
          key={g.id}
          group={g}
          active={s.active?.groupId === g.id ? s.active.model : null}
          fetchState={fetchState[g.id] ?? { status: "idle" }}
          onChange={(patch) => update(g.id, patch)}
          onRemove={() => removeGroup(g)}
          onFetch={() => fetchModels(g)}
          onSelect={(model) => commit({ ...s, active: { groupId: g.id, model } })}
        />
      ))}

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted-foreground">{t("Add a group:", "添加分组：")}</span>
        {API_TYPES.map((a) => (
          <Button key={a} size="sm" variant="outline" onClick={() => addGroup(a)}><Plus /> {API_META[a].label}</Button>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t("Network", "网络")}</CardTitle>
          <CardDescription>
            {t("Optional HTTP proxy for model calls. Blank uses the server default.", "访问模型服务的 HTTP 代理（可选），留空则使用服务器默认设置。")}
            {proxyLoaded && <> <Badge variant="success">{t("server proxy active", "服务器代理已启用")}</Badge></>}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <input className={cn(inputCls, "font-mono text-[13px]")} placeholder="http://user:pass@host:3128" value={s.proxy}
            onChange={(e) => commit({ ...s, proxy: e.target.value.trim() })} />
        </CardContent>
      </Card>

      {me?.role === "admin" && <RatesPanel />}
      {me?.role === "admin" && <NewsPanel />}

      {importOpen && (
        <ImportDialog
          onClose={() => setImportOpen(false)}
          onImport={(imp) => {
            commit(mergeImport(loadSettings(), imp));
            setImportOpen(false);
          }}
        />
      )}
      {exportOpen && <ExportDialog settings={s} onClose={() => setExportOpen(false)} />}
    </div>
  );
}

function ImportDialog({ onClose, onImport }: { onClose: () => void; onImport: (imp: Imported) => void }) {
  const t = useT();
  const [text, setText] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const parsed = useMemo(() => {
    if (!text.trim()) return null;
    try {
      return { ok: true as const, imp: parseImport(text) };
    } catch (e) {
      return { ok: false as const, error: (e as Error).message };
    }
  }, [text]);

  return (
    <Modal title={t("Import model groups", "导入模型分组")} onClose={onClose}>
      <p className="text-[13px] text-muted-foreground">
        {t("Paste or choose a file: a QFinZero export, a Claude Code settings.json, export ANTHROPIC_* lines, or a Codex config.toml.",
           "粘贴或选择文件：QFinZero 导出文件、Claude Code 的 settings.json、export ANTHROPIC_* 环境变量，或 Codex 的 config.toml。")}
      </p>
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={9} spellCheck={false}
        className="w-full rounded-md border border-input bg-card p-2 font-mono text-xs outline-none focus:border-ring" />
      <input ref={fileRef} type="file" accept=".json,.toml,.env,.txt,.sh" className="hidden"
        onChange={async (e) => { const f = e.target.files?.[0]; if (f) setText(await f.text()); }} />
      {parsed?.ok === false && <Alert variant="error">{parsed.error}</Alert>}
      {parsed?.ok && (
        <Alert variant="success" title={t(`Found ${parsed.imp.groups.length} group(s)`, `识别到 ${parsed.imp.groups.length} 个分组`)}>
          {parsed.imp.groups.map((g) => `${g.name} (${API_META[g.api].label}${g.apiKey ? t(", with key", "，含密钥") : ""})`).join("; ")}
          {parsed.imp.active && t(` · active model ${parsed.imp.active.model}`, ` · 当前模型 ${parsed.imp.active.model}`)}
        </Alert>
      )}
      <div className="flex justify-between gap-2">
        <Button size="sm" variant="ghost" onClick={() => fileRef.current?.click()}><FileUp /> {t("Choose file", "选择文件")}</Button>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={onClose}>{t("Cancel", "取消")}</Button>
          <Button size="sm" disabled={!parsed?.ok} onClick={() => parsed?.ok && onImport(parsed.imp)}>{t("Import", "导入")}</Button>
        </div>
      </div>
    </Modal>
  );
}

function ExportDialog({ settings, onClose }: { settings: ModelSettings; onClose: () => void }) {
  const t = useT();
  const [keys, setKeys] = useState(false);
  const json = exportJson(settings, keys);
  const download = () => {
    const url = URL.createObjectURL(new Blob([json], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "qfinzero-model-groups.json";
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <Modal title={t("Export model groups", "导出模型分组")} onClose={onClose}>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={keys} onChange={(e) => setKeys(e.target.checked)} />
        {t("Include API keys", "包含 API 密钥")}
      </label>
      {keys && <Alert variant="warning">{t("The file will contain your keys in plain text. Store it like a password.", "文件将以明文包含密钥，请像保管密码一样保管它。")}</Alert>}
      <pre className="max-h-64 overflow-auto rounded-md border bg-muted/40 p-2 font-mono text-[11.5px]">{json}</pre>
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="outline" onClick={() => navigator.clipboard.writeText(json)}>{t("Copy", "复制")}</Button>
        <Button size="sm" onClick={download}><Download /> {t("Download", "下载")}</Button>
      </div>
    </Modal>
  );
}
