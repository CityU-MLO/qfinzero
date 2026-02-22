"use client";

import { cn } from "@/lib/utils";
import { Streamdown } from "streamdown";
import "streamdown/styles.css";
import { ToolCallCard, ToolCallData } from "./tool-call-card";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  toolCalls?: ToolCallData[];
}

interface MessageBubbleProps {
  message: ChatMessage;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";

  return (
    <div className={cn("flex flex-col gap-2", isUser ? "items-end" : "items-start")}>
      {/* Tool calls (assistant only, shown above text) */}
      {!isUser && message.toolCalls && message.toolCalls.length > 0 && (
        <div className="flex flex-col gap-1.5 w-full max-w-[90%]">
          {message.toolCalls.map((call) => (
            <ToolCallCard key={call.id} call={call} />
          ))}
        </div>
      )}

      {/* Message text */}
      {message.content && (
        <div
          className={cn(
            "rounded-2xl px-4 py-2.5 text-sm max-w-[90%] leading-relaxed",
            isUser
              ? "bg-primary text-primary-foreground rounded-br-sm"
              : "bg-white border text-foreground rounded-bl-sm"
          )}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : (
            <Streamdown>{message.content}</Streamdown>
          )}
        </div>
      )}
    </div>
  );
}
