"use client";

import { useRef, useState, useEffect, useCallback } from "react";
import { Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { PlaygroundConfig } from "./config-panel";
import { MessageBubble, ChatMessage } from "./message-bubble";
import { ToolCallData } from "./tool-call-card";

interface ChatPanelProps {
  config: PlaygroundConfig;
}

function makeId() {
  return Math.random().toString(36).slice(2);
}

export function ChatPanel({ config }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const pendingByTool = useRef<Record<string, string[]>>({});
  // One thread_id per browser session — stable across messages in this conversation
  const threadId = useRef<string>(Math.random().toString(36).slice(2));

  // Auto-scroll to bottom
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;

    setInput("");
    setStreaming(true);

    // Add user message
    const userMsg: ChatMessage = { id: makeId(), role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);

    // Add empty assistant message placeholder
    const assistantId = makeId();
    const assistantMsg: ChatMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      toolCalls: [],
    };
    setMessages((prev) => [...prev, assistantMsg]);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch("/api/playground/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          thread_id: threadId.current,
          messages: [{ role: "user", content: text }],
          model: config.model,
          base_url: config.baseUrl,
          api_key: config.apiKey,
          as_of_date: config.asOfDate,
        }),
        signal: controller.signal,
      });

      if (!res.ok || !res.body) {
        throw new Error(`HTTP ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      // Reset FIFO queue for this request
      pendingByTool.current = {};

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6).trim();
          if (!raw) continue;

          let event: Record<string, unknown>;
          try {
            event = JSON.parse(raw);
          } catch {
            continue;
          }

          const type = event.type as string;

          if (type === "tool_start") {
            const callId = makeId();
            const toolName = event.tool as string;
            if (!pendingByTool.current[toolName]) {
              pendingByTool.current[toolName] = [];
            }
            pendingByTool.current[toolName].push(callId);
            const call: ToolCallData = {
              id: callId,
              tool: toolName,
              input: event.input as Record<string, unknown>,
              status: "loading",
            };
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, toolCalls: [...(m.toolCalls ?? []), call] }
                  : m
              )
            );
          } else if (type === "tool_end") {
            const toolName = event.tool as string;
            const callId = pendingByTool.current[toolName]?.shift();
            if (callId) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? {
                        ...m,
                        toolCalls: (m.toolCalls ?? []).map((c) =>
                          c.id === callId
                            ? { ...c, output: event.output, status: "done" as const }
                            : c
                        ),
                      }
                    : m
                )
              );
            }
          } else if (type === "llm_chunk") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, content: m.content + (event.content as string) }
                  : m
              )
            );
          } else if (type === "error") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, content: `Error: ${event.message as string}` }
                  : m
              )
            );
          }
          // "done" event: nothing to do, streaming will end
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, content: `Connection error: ${(err as Error).message}` }
              : m
          )
        );
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }, [input, streaming, messages, config]);

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void sendMessage();
    }
  }

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Message list */}
      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-4">
        {messages.length === 0 && (
          <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
            Ask anything about market data, news, or trading...
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="border-t p-3 flex gap-2 items-end bg-white/80">
        <Textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type your question... (Enter to send, Shift+Enter for newline)"
          className="resize-none text-sm min-h-[40px] max-h-[120px]"
          rows={1}
          disabled={streaming}
        />
        <Button
          onClick={() => void sendMessage()}
          disabled={streaming || !input.trim()}
          size="icon"
          className="shrink-0 h-10 w-10"
        >
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
