"use client";

import { useEffect, useMemo, useRef, type PropsWithChildren } from "react";
import {
  AssistantRuntimeProvider,
  AuiIf,
  ComposerPrimitive,
  MessagePartPrimitive,
  MessagePrimitive,
  RuntimeAdapterProvider,
  ThreadListItemPrimitive,
  ThreadListPrimitive,
  ThreadPrimitive,
  unstable_useRemoteThreadListRuntime,
  useAui,
  useLocalRuntime,
  useMessagePartText,
  type ChatModelAdapter,
  type ExportedMessageRepository,
  type ExportedMessageRepositoryItem,
  type ThreadHistoryAdapter,
  type ThreadMessage,
  type unstable_RemoteThreadListAdapter,
} from "@assistant-ui/react";
import { createAssistantStream } from "assistant-stream";
import { Send, Square, Plus, Trash2, ChevronDown } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

import { cn } from "@/lib/utils";
import {
  PLAYGROUND_HISTORY_DEFAULT_TITLE,
  deriveThreadTitleFromMessage,
  ensureThread,
  loadThreadRepository,
  loadThreads,
  maybeAutoTitleThread,
  removeThread,
  renameThread,
  setThreadStatus,
  touchThread,
  type StoredThreadMessage,
} from "@/lib/playground-history";
import { normalizeMathDelimiters } from "@/lib/playground-math";
import type { PlaygroundConfig } from "./config-panel";

interface PlaygroundAssistantProps {
  config: PlaygroundConfig;
}

type PlaygroundSseEvent = {
  type?: string;
  content?: string;
  message?: string;
};

function makeId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2);
}

function extractTextFromThreadMessage(message: ThreadMessage | undefined): string {
  if (!message) return "";
  return message.content
    .map((part) => {
      if (part.type === "text") return part.text;
      return "";
    })
    .filter(Boolean)
    .join("\n")
    .trim();
}

function extractFirstUserTitle(messages: readonly ThreadMessage[]): string {
  const firstUser = messages.find((message) => message.role === "user");
  if (!firstUser) return PLAYGROUND_HISTORY_DEFAULT_TITLE;
  return deriveThreadTitleFromMessage(firstUser as unknown as StoredThreadMessage);
}

function parseSseEventLine(line: string): PlaygroundSseEvent | null {
  if (!line.startsWith("data: ")) return null;
  const raw = line.slice(6).trim();
  if (!raw) return null;

  try {
    return JSON.parse(raw) as PlaygroundSseEvent;
  } catch {
    return null;
  }
}

function upsertRepositoryItem(threadId: string, item: ExportedMessageRepositoryItem) {
  const repository = loadThreadRepository(threadId) as unknown as ExportedMessageRepository;
  const filtered = repository.messages.filter((entry) => entry.message.id !== item.message.id);
  filtered.push(item);

  const nextRepository: ExportedMessageRepository = {
    headId: item.message.id,
    messages: filtered,
  };

  localStorage.setItem(`playground_thread_messages_v1:${threadId}`, JSON.stringify(nextRepository.messages.map((entry) => entry.message)));
}

function LocalHistoryProvider({ children }: PropsWithChildren) {
  const aui = useAui();

  const history = useMemo<ThreadHistoryAdapter>(
    () => ({
      async load() {
        const { remoteId } = aui.threadListItem().getState();
        if (!remoteId) return { messages: [] };
        return loadThreadRepository(remoteId) as unknown as ExportedMessageRepository;
      },
      async append(item) {
        const { remoteId } = await aui.threadListItem().initialize();
        ensureThread(remoteId);
        upsertRepositoryItem(remoteId, item);
        maybeAutoTitleThread(remoteId, item.message as unknown as StoredThreadMessage);
        touchThread(remoteId);
      },
      async update(item: ExportedMessageRepositoryItem, _localMessageId: string) {
        const { remoteId } = await aui.threadListItem().initialize();
        ensureThread(remoteId);
        upsertRepositoryItem(remoteId, item);
        touchThread(remoteId);
      },
    }),
    [aui]
  );

  return <RuntimeAdapterProvider adapters={{ history }}>{children}</RuntimeAdapterProvider>;
}

function usePlaygroundThreadListAdapter(): unstable_RemoteThreadListAdapter {
  return useMemo<unstable_RemoteThreadListAdapter>(
    () => ({
      async list() {
        return {
          threads: loadThreads().map((thread) => ({
            status: thread.status,
            remoteId: thread.id,
            title: thread.title,
          })),
        };
      },
      async initialize(threadId) {
        ensureThread(threadId);
        return { remoteId: threadId, externalId: undefined };
      },
      async rename(remoteId, newTitle) {
        renameThread(remoteId, newTitle);
      },
      async archive(remoteId) {
        setThreadStatus(remoteId, "archived");
      },
      async unarchive(remoteId) {
        setThreadStatus(remoteId, "regular");
      },
      async delete(remoteId) {
        removeThread(remoteId);
      },
      async fetch(threadId) {
        const thread = loadThreads().find((entry) => entry.id === threadId);
        if (!thread) throw new Error("Thread not found");
        return {
          status: thread.status,
          remoteId: thread.id,
          title: thread.title,
        };
      },
      async generateTitle(remoteId, messages) {
        const generated = extractFirstUserTitle(messages);
        renameThread(remoteId, generated);

        return createAssistantStream((controller) => {
          controller.appendText(generated);
          controller.close();
        });
      },
      unstable_Provider: LocalHistoryProvider,
    }),
    []
  );
}

function usePlaygroundModelAdapter(config: PlaygroundConfig): ChatModelAdapter {
  const configRef = useRef(config);

  useEffect(() => {
    configRef.current = config;
  }, [config]);

  return useMemo<ChatModelAdapter>(
    () => ({
      async *run({ messages, abortSignal, unstable_threadId }) {
        const live = configRef.current;
        const latestUser = [...messages].reverse().find((message) => message.role === "user");
        const userText = extractTextFromThreadMessage(latestUser);
        const threadId = unstable_threadId ?? makeId();

        if (!userText) {
          return;
        }

        const response = await fetch("/api/playground/chat", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            thread_id: threadId,
            messages: [{ role: "user", content: userText }],
            model: live.model,
            base_url: live.baseUrl,
            api_key: live.apiKey,
            as_of_date: live.asOfDate,
          }),
          signal: abortSignal,
        });

        if (!response.ok || !response.body) {
          throw new Error(`HTTP ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let fullText = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            const event = parseSseEventLine(line);
            if (!event) continue;

            if (event.type === "llm_chunk") {
              fullText += event.content ?? "";
              yield {
                content: [{ type: "text", text: normalizeMathDelimiters(fullText) }],
              };
            }

            if (event.type === "error") {
              throw new Error(event.message ?? "Upstream error");
            }
          }
        }
      },
    }),
    []
  );
}

function AssistantMarkdownText() {
  const part = useMessagePartText();

  return (
    <div className="text-sm leading-relaxed [&_p]:mb-2 [&_p:last-child]:mb-0 [&_.katex-display]:overflow-x-auto [&_.katex-display]:overflow-y-hidden">
      <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
        {normalizeMathDelimiters(part.text)}
      </ReactMarkdown>
      <MessagePartPrimitive.InProgress>
        <span className="inline-block ml-1 animate-pulse">●</span>
      </MessagePartPrimitive.InProgress>
    </div>
  );
}

function UserMessage() {
  return (
    <MessagePrimitive.Root className="flex justify-end px-4 py-2">
      <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-4 py-2.5 text-sm text-primary-foreground">
        <MessagePrimitive.Parts />
      </div>
    </MessagePrimitive.Root>
  );
}

function AssistantMessage() {
  return (
    <MessagePrimitive.Root className="flex justify-start px-4 py-2">
      <div className="max-w-[90%] rounded-2xl rounded-bl-sm border bg-white px-4 py-2.5 text-foreground shadow-sm">
        <MessagePrimitive.Parts components={{ Text: AssistantMarkdownText }} />
      </div>
    </MessagePrimitive.Root>
  );
}

function ChatComposer() {
  return (
    <ComposerPrimitive.Root className="border-t bg-white/80 p-3">
      <div className="flex items-end gap-2">
        <ComposerPrimitive.Input
          placeholder="Type your question... (Enter to send, Shift+Enter for newline)"
          className="min-h-[42px] max-h-[140px] flex-1 overflow-y-auto rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none ring-offset-background transition-[color,box-shadow] placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
          autoFocus
          rows={1}
        />

        <AuiIf condition={(state) => state.thread.isRunning}>
          <ComposerPrimitive.Cancel className="inline-flex h-10 w-10 items-center justify-center rounded-lg border bg-background text-foreground transition-colors hover:bg-accent hover:text-accent-foreground">
            <Square className="h-4 w-4" />
          </ComposerPrimitive.Cancel>
        </AuiIf>

        <AuiIf condition={(state) => !state.thread.isRunning}>
          <ComposerPrimitive.Send className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-primary text-primary-foreground transition-colors hover:opacity-90 disabled:opacity-50">
            <Send className="h-4 w-4" />
          </ComposerPrimitive.Send>
        </AuiIf>
      </div>
    </ComposerPrimitive.Root>
  );
}

function HistoryThreadItem() {
  return (
    <ThreadListItemPrimitive.Root className="group flex items-center gap-1 rounded-lg border border-transparent px-1 py-1 data-[active=true]:border-primary/30 data-[active=true]:bg-primary/10">
      <ThreadListItemPrimitive.Trigger className="flex-1 truncate rounded-md px-2 py-1.5 text-left text-sm text-foreground transition-colors hover:bg-accent hover:text-accent-foreground">
        <ThreadListItemPrimitive.Title fallback={PLAYGROUND_HISTORY_DEFAULT_TITLE} />
      </ThreadListItemPrimitive.Trigger>
      <ThreadListItemPrimitive.Delete className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100">
        <Trash2 className="h-3.5 w-3.5" />
      </ThreadListItemPrimitive.Delete>
    </ThreadListItemPrimitive.Root>
  );
}

function HistorySidebar() {
  return (
    <aside className="flex h-full w-[270px] shrink-0 flex-col border-r bg-white/60 p-3">
      <div className="mb-3 flex items-center justify-between px-1">
        <h2 className="text-xs font-bold uppercase tracking-widest text-muted-foreground">History</h2>
        <ThreadListPrimitive.New className="inline-flex h-8 items-center gap-1 rounded-md border px-2 text-xs font-medium text-foreground transition-colors hover:bg-accent hover:text-accent-foreground">
          <Plus className="h-3.5 w-3.5" />
          New
        </ThreadListPrimitive.New>
      </div>

      <ThreadListPrimitive.Root className="flex min-h-0 flex-1 flex-col">
        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto pr-1">
          <ThreadListPrimitive.Items components={{ ThreadListItem: HistoryThreadItem }} />
        </div>
      </ThreadListPrimitive.Root>
    </aside>
  );
}

function AssistantThread() {
  return (
    <ThreadPrimitive.Root className="flex min-h-0 flex-1 flex-col">
      <ThreadPrimitive.Viewport className="relative min-h-0 flex-1 overflow-y-auto py-3">
        <AuiIf condition={(state) => state.thread.isEmpty}>
          <div className="flex h-full items-center justify-center px-8 text-center text-sm text-muted-foreground">
            Ask anything about market data, news, Greeks, or trading.
          </div>
        </AuiIf>

        <ThreadPrimitive.Messages
          components={{
            UserMessage,
            AssistantMessage,
          }}
        />

        <ThreadPrimitive.ScrollToBottom className={cn(
          "absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full border bg-white px-3 py-1 text-xs text-muted-foreground shadow-sm transition-opacity hover:text-foreground",
          "data-[visible=false]:pointer-events-none data-[visible=false]:opacity-0",
          "data-[visible=true]:opacity-100"
        )}>
          <ChevronDown className="mr-1 inline h-3.5 w-3.5" />
          Jump to latest
        </ThreadPrimitive.ScrollToBottom>
      </ThreadPrimitive.Viewport>

      <ChatComposer />
    </ThreadPrimitive.Root>
  );
}

export function PlaygroundAssistant({ config }: PlaygroundAssistantProps) {
  const modelAdapter = usePlaygroundModelAdapter(config);
  const threadListAdapter = usePlaygroundThreadListAdapter();

  const runtime = unstable_useRemoteThreadListRuntime({
    runtimeHook: function RuntimeHook() {
      return useLocalRuntime(modelAdapter);
    },
    adapter: threadListAdapter,
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="flex min-h-0 flex-1 overflow-hidden rounded-2xl border bg-white/80 shadow-sm">
        <HistorySidebar />
        <AssistantThread />
      </div>
    </AssistantRuntimeProvider>
  );
}
