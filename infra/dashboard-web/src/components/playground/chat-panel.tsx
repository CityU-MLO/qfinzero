"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUp, Download, FoldVertical, Loader2, PanelLeft, Settings2, Square } from "lucide-react";

import { useT } from "@/components/locale-provider";
import {
  applyEvent, chatApi, fmtTokens, streamChat,
  type ChatMessage, type ContextUsage, type LlmFields, type StreamEvent,
} from "@/lib/chat-api";
import { cn } from "@/lib/utils";

import { PlaygroundConfig, utcToDatetimeLocal } from "./config-panel";
import { MessageBubble } from "./message-bubble";
import { RunInspector } from "./run-inspector";

export const DEFAULT_CONTEXT = 128_000;

function llmFields(c: PlaygroundConfig): LlmFields {
  return { api: c.api ?? "openai", model: c.model, base_url: c.baseUrl, api_key: c.apiKey, proxy: c.proxy || undefined };
}

function ContextMeter({ usage, onCompact, compacting }: { usage: ContextUsage | null; onCompact: () => void; compacting: boolean }) {
  const t = useT();
  if (!usage) return null;
  const pct = Math.min(100, (usage.total / usage.budget) * 100);
  const tone = pct > 80 ? "bg-destructive" : pct > 60 ? "bg-warning" : "bg-primary";
  const title = [
    t(`Estimated context ${usage.total.toLocaleString()} / ${usage.budget.toLocaleString()} tokens`,
      `估算上下文 ${usage.total.toLocaleString()} / ${usage.budget.toLocaleString()} token`),
    t(`system ${usage.system} · summary ${usage.summary} · messages ${usage.messages}`,
      `系统 ${usage.system} · 摘要 ${usage.summary} · 消息 ${usage.messages}`),
    t(`${usage.messages_in_context} messages in context, ${usage.compacted_messages} compacted`,
      `${usage.messages_in_context} 条消息在上下文中，${usage.compacted_messages} 条已压缩`),
    usage.last_input_tokens != null ? t(`last request: ${usage.last_input_tokens.toLocaleString()} input tokens (reported by the model)`,
      `上次请求：${usage.last_input_tokens.toLocaleString()} 输入 token（模型返回）`) : "",
  ].filter(Boolean).join("\n");
  return (
    <div className="flex items-center gap-2" title={title}>
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full rounded-full", tone)} style={{ width: `${pct}%` }} />
      </div>
      <span className="whitespace-nowrap text-[11px] tabular-nums text-muted-foreground">
        ≈{fmtTokens(usage.total)} / {fmtTokens(usage.budget)}
        {usage.compacted_messages > 0 && ` · ${t("compacted", "已压缩")} ${usage.compacted_messages}`}
      </span>
      <button onClick={onCompact} disabled={compacting || usage.messages_in_context < 3}
        className="flex items-center gap-1 rounded px-1.5 py-1 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
        title={t("Summarise older turns now to free context", "立即总结较早的对话以释放上下文")}>
        {compacting ? <Loader2 className="h-3 w-3 animate-spin" /> : <FoldVertical className="h-3 w-3" />}
        <span className="hidden whitespace-nowrap xl:inline">{t("Compact", "压缩")}</span>
      </button>
    </div>
  );
}

const SUGGESTIONS: [string, string][] = [
  ["How did SPY trade in its first 30 minutes today? Use minute bars.", "SPY 今天开盘 30 分钟走势如何？用分钟线分析。"],
  ["What news moved NVDA this week, and how did the stock react?", "本周有哪些新闻影响了 NVDA，股价如何反应？"],
  ["Open a $50,000 paper account and buy 1 ZN future at the market.", "开一个 5 万美元的模拟账户，市价买入 1 手 ZN 期货。"],
  ["Which macro releases are due in the next two days?", "未来两天有哪些宏观数据发布？"],
];

export function ChatPanel({ config, threadId, onThread, onThreadsChanged, onToggleSettings, onToggleSidebar }: {
  onToggleSidebar: () => void;
  config: PlaygroundConfig;
  threadId: string | null;
  onThread: (id: string | null) => void;
  onThreadsChanged: () => void;
  onToggleSettings: () => void;
}) {
  const t = useT();
  const [title, setTitle] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [live, setLive] = useState<ChatMessage | null>(null);
  const [running, setRunning] = useState(false);
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [usage, setUsage] = useState<ContextUsage | null>(null);
  const [compacting, setCompacting] = useState(false);
  const [inspect, setInspect] = useState<{ msg: ChatMessage; user: string } | null>(null);
  const [exportOpen, setExportOpen] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const abortRef = useRef<AbortController | null>(null);
  const skipLoad = useRef<string | null>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const budget = config.contextTokens ?? DEFAULT_CONTEXT;

  const refreshUsage = useCallback(async (id: string | null) => {
    if (!id) return setUsage(null);
    try { setUsage(await chatApi.context(id, budget, config.asOfDate)); } catch { /* optional */ }
  }, [budget, config.asOfDate]);

  const load = useCallback(async (id: string) => {
    try {
      const d = await chatApi.get(id);
      setTitle(d.thread.title);
      setMessages(d.messages);
      setLive(d.live);
      setRunning(d.running);
      setError(null);
      return d.running;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return false;
    }
  }, []);

  // open a thread (or a blank one)
  useEffect(() => {
    if (threadId && skipLoad.current === threadId) { skipLoad.current = null; return; }
    abortRef.current?.abort();
    setInspect(null);
    if (!threadId) {
      setTitle(""); setMessages([]); setLive(null); setRunning(false); setUsage(null); setError(null);
      return;
    }
    stickRef.current = true;
    void load(threadId).then(() => refreshUsage(threadId));
  }, [threadId, load, refreshUsage]);

  // a turn running without our stream (another tab, or after a reload): poll until it ends
  useEffect(() => {
    if (!threadId || !running || abortRef.current) return;
    const h = setInterval(async () => {
      const still = await load(threadId);
      if (!still) { clearInterval(h); onThreadsChanged(); void refreshUsage(threadId); }
    }, 1500);
    return () => clearInterval(h);
  }, [threadId, running, load, onThreadsChanged, refreshUsage]);

  useEffect(() => {
    if (stickRef.current) bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages, live]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (el) stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  const send = useCallback(async (raw?: string) => {
    const text = (raw ?? input).trim();
    if (!text || running) return;
    if (!config.model) { setError(t("Choose a model in the settings first.", "请先在设置中选择模型。")); return; }
    setInput("");
    setError(null);
    setNotice(null);
    stickRef.current = true;
    const now = Date.now() / 1000;
    setMessages((m) => [...m, { id: `tmp_${now}`, role: "user", content: text, steps: [], status: "complete", created_at: now }]);
    setLive({ id: "live", role: "assistant", content: "", steps: [], status: "running", model: config.model, created_at: now });
    setRunning(true);
    const controller = new AbortController();
    abortRef.current = controller;
    let tid = threadId;
    try {
      await streamChat({
        thread_id: threadId, messages: [{ role: "user", content: text }], ...llmFields(config),
        as_of_date: config.asOfDate, context_tokens: budget, auto_compact: config.autoCompact ?? true,
      }, (e: StreamEvent) => {
        if (e.type === "turn_start") {
          tid = e.thread_id as string;
          const user = e.user as ChatMessage;
          setMessages((m) => m.map((x) => (x.id.startsWith("tmp_") ? user : x)));
          if (tid !== threadId) { skipLoad.current = tid; onThread(tid); }
          onThreadsChanged();
        } else if (e.type === "compacted") {
          setNotice(t(`Compacted ${e.messages} earlier messages into a summary to fit the context.`,
            `已将较早的 ${e.messages} 条消息压缩为摘要，以适应上下文。`));
        } else if (e.type === "done" || e.type === "interrupted" || e.type === "error") {
          const saved = e.message as ChatMessage | undefined;
          if (saved) setMessages((m) => [...m, saved]);
          setLive(null);
        } else {
          setLive((m) => (m ? applyEvent(m, e) : m));
        }
      }, controller.signal);
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError((err as Error).message);
        setLive(null);
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setRunning(false);
      if (tid) { void load(tid); void refreshUsage(tid); setTitle((x) => x || text.slice(0, 48)); }
      onThreadsChanged();
    }
  }, [input, running, config, threadId, budget, onThread, onThreadsChanged, load, refreshUsage, t]);

  const stop = useCallback(async () => {
    if (!threadId) { abortRef.current?.abort(); return; }
    try { await chatApi.interrupt(threadId); } catch (e) { setError((e as Error).message); }
  }, [threadId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && running && !inspect) { e.preventDefault(); void stop(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [running, stop, inspect]);

  // auto-grow the composer
  useEffect(() => {
    const el = textRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }, [input]);

  async function compact() {
    if (!threadId) return;
    setCompacting(true);
    try {
      const r = await chatApi.compact(threadId, llmFields(config));
      setNotice(r.ok ? t(`Compacted ${r.compacted_messages} messages into a summary.`, `已将 ${r.compacted_messages} 条消息压缩为摘要。`)
        : r.error ?? "");
      await refreshUsage(threadId);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCompacting(false);
    }
  }

  async function rename() {
    if (!threadId) return;
    const next = window.prompt(t("Rename this chat", "重命名对话"), title);
    if (next && next.trim()) {
      await chatApi.rename(threadId, next.trim());
      setTitle(next.trim());
      onThreadsChanged();
    }
  }

  const all = live ? [...messages, live] : messages;
  const userBefore = (i: number) => {
    for (let k = i - 1; k >= 0; k--) if (all[k].role === "user") return all[k].content;
    return "";
  };

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      {/* header */}
      <div className="flex h-12 shrink-0 items-center justify-between gap-3 border-b px-4">
        <div className="flex min-w-0 items-center gap-2">
          <button onClick={onToggleSidebar} className="rounded p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
            title={t("Show or hide chats", "显示或隐藏对话列表")} aria-label={t("Chats", "对话列表")}>
            <PanelLeft className="h-4 w-4" />
          </button>
          <button onClick={rename} disabled={!threadId} title={title}
            className="min-w-0 truncate text-sm font-medium text-foreground hover:underline disabled:no-underline">
            {title || t("New chat", "新对话")}
          </button>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <ContextMeter usage={usage} onCompact={compact} compacting={compacting} />
          {threadId && (
            <div className="relative">
              <button onClick={() => setExportOpen(!exportOpen)}
                className="flex items-center gap-1 rounded px-1.5 py-1 text-[12px] text-muted-foreground hover:bg-muted hover:text-foreground">
                <Download className="h-3.5 w-3.5" /> <span className="hidden whitespace-nowrap xl:inline">{t("Export", "导出")}</span>
              </button>
              {exportOpen && (
                <div className="absolute right-0 top-8 z-20 w-52 rounded-md border bg-card p-1 shadow-md" onMouseLeave={() => setExportOpen(false)}>
                  <a href={chatApi.exportUrl(threadId, true)} onClick={() => setExportOpen(false)}
                    className="block rounded px-2 py-1.5 text-[13px] hover:bg-muted">{t("Markdown with tool calls", "Markdown（含工具调用）")}</a>
                  <a href={chatApi.exportUrl(threadId, false)} onClick={() => setExportOpen(false)}
                    className="block rounded px-2 py-1.5 text-[13px] hover:bg-muted">{t("Markdown, text only", "Markdown（仅文字）")}</a>
                </div>
              )}
            </div>
          )}
          <button onClick={onToggleSettings} className="rounded p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
            title={t("Model and context settings", "模型与上下文设置")} aria-label={t("Settings", "设置")}>
            <Settings2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* messages */}
      <div ref={scrollRef} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-6">
          {all.length === 0 && (
            <div className="flex flex-col items-center gap-4 pt-16 text-center">
              <div className="text-lg font-semibold text-foreground">{t("What should we look into?", "今天想研究什么？")}</div>
              <p className="max-w-md text-[13px] text-muted-foreground">
                {t("The assistant reads market data, news and events up to the simulation time, and can trade in the paper broker.",
                  "助手可以读取模拟时间之前的行情、新闻和事件，也可以在模拟券商中交易。")}
              </p>
              <div className="grid w-full max-w-xl gap-2 sm:grid-cols-2">
                {SUGGESTIONS.map(([en, zh]) => (
                  <button key={en} onClick={() => void send(t(en, zh))}
                    className="rounded-lg border bg-card px-3 py-2 text-left text-[13px] text-muted-foreground transition hover:bg-muted hover:text-foreground">
                    {t(en, zh)}
                  </button>
                ))}
              </div>
            </div>
          )}
          {all.map((m, i) => (
            <MessageBubble key={m.id} message={m}
              onInspect={m.role === "assistant" ? () => setInspect({ msg: m, user: userBefore(i) }) : undefined} />
          ))}
          {notice && <div className="text-center text-[12px] text-muted-foreground">{notice}</div>}
          {error && (
            <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-[13px] text-destructive">{error}</div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* composer */}
      <div className="shrink-0 px-4 pb-4">
        <div className="mx-auto max-w-3xl">
          <div className="flex items-end gap-2 rounded-2xl border bg-card px-3 py-2 shadow-sm focus-within:ring-2 focus-within:ring-ring/20">
            <textarea ref={textRef} value={input} rows={1}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); }
              }}
              placeholder={running ? t("Answering… press Esc or ■ to stop", "正在回答……按 Esc 或 ■ 停止")
                : t("Ask about market data, news or trading (Enter to send, Shift+Enter for a new line)",
                  "询问行情、新闻或交易（Enter 发送，Shift+Enter 换行）")}
              className="max-h-[220px] min-h-[24px] flex-1 resize-none bg-transparent py-1 text-sm outline-none" />
            {running ? (
              <button onClick={() => void stop()} className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-foreground text-background"
                title={t("Stop (Esc)", "停止（Esc）")} aria-label={t("Stop", "停止")}>
                <Square className="h-3.5 w-3.5 fill-current" />
              </button>
            ) : (
              <button onClick={() => void send()} disabled={!input.trim()}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground disabled:opacity-40"
                title={t("Send", "发送")} aria-label={t("Send", "发送")}>
                <ArrowUp className="h-4 w-4" />
              </button>
            )}
          </div>
          <div className="mt-1.5 flex justify-between px-1 text-[11px] text-muted-foreground">
            <span className="truncate font-mono">{config.model || t("no model selected", "未选择模型")}</span>
            <span>{t("Simulation time", "模拟时间")} {utcToDatetimeLocal(config.asOfDate).replace("T", " ")} ET</span>
          </div>
        </div>
      </div>

      {inspect && <RunInspector message={inspect.msg} userText={inspect.user} onClose={() => setInspect(null)} />}
    </div>
  );
}
