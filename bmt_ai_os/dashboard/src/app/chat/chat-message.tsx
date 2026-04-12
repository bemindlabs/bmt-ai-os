"use client";

import { useState, useEffect } from "react";
import { Bot, User } from "lucide-react";
import { SourceList } from "@/components/source-card";
import { MarkdownContent } from "./chat-markdown";
import { cn } from "@/lib/utils";
import type { ChatMessage, RagSource } from "@/lib/api";

// ─── Types ────────────────────────────────────────────────────────────────────

/** ChatMessage extended with local metadata */
export interface LocalMessage extends ChatMessage {
  id: string;
  timestamp: Date;
  tokens: number;
  sources?: RagSource[];
}

/** A consecutive run of messages from the same role */
export interface MessageGroup {
  role: "user" | "assistant" | "system";
  messages: LocalMessage[];
  groupTimestamp: Date;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

export function groupMessages(messages: LocalMessage[]): MessageGroup[] {
  const groups: MessageGroup[] = [];
  for (const msg of messages) {
    const last = groups[groups.length - 1];
    if (last && last.role === msg.role) {
      last.messages.push(msg);
    } else {
      groups.push({
        role: msg.role as "user" | "assistant" | "system",
        messages: [msg],
        groupTimestamp: msg.timestamp,
      });
    }
  }
  return groups;
}

function relativeTime(date: Date): string {
  const diffMs = Date.now() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 5) return "just now";
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin} min ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return date.toLocaleDateString();
}

// ─── TokenBadge ───────────────────────────────────────────────────────────────

function TokenBadge({ tokens }: { tokens: number }) {
  return (
    <span
      className="ml-1.5 inline-flex items-center rounded px-1 py-0 text-[10px] font-medium tabular-nums bg-muted text-muted-foreground"
      title={`~${tokens.toLocaleString()} tokens`}
    >
      ~{tokens >= 1000 ? `${(tokens / 1000).toFixed(1)}k` : tokens}t
    </span>
  );
}

// ─── MessageGroupRow ──────────────────────────────────────────────────────────

interface MessageGroupRowProps {
  group: MessageGroup;
}

export function MessageGroupRow({ group }: MessageGroupRowProps) {
  const isUser = group.role === "user";
  const [, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 30_000);
    return () => clearInterval(id);
  }, []);

  return (
    <div
      className={cn("flex gap-2.5", isUser ? "flex-row-reverse" : "flex-row")}
    >
      {/* Avatar */}
      <div
        className={cn(
          "mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full text-xs",
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-muted text-muted-foreground",
        )}
        aria-hidden="true"
      >
        {isUser ? <User className="size-3.5" /> : <Bot className="size-3.5" />}
      </div>

      {/* Bubble stack */}
      <div
        className={cn(
          "flex max-w-[75%] flex-col gap-1",
          isUser ? "items-end" : "items-start",
        )}
      >
        {group.messages.map((msg) => (
          <div key={msg.id} className="flex flex-col gap-1 w-full">
            <div
              className={cn(
                "rounded-xl px-3.5 py-2.5 text-sm leading-relaxed",
                isUser
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-foreground",
              )}
            >
              {isUser ? (
                <span className="whitespace-pre-wrap">{msg.content}</span>
              ) : (
                <MarkdownContent content={msg.content} />
              )}
              <TokenBadge tokens={msg.tokens} />
            </div>
            {/* RAG sources below assistant message */}
            {!isUser && msg.sources && msg.sources.length > 0 && (
              <SourceList sources={msg.sources} />
            )}
          </div>
        ))}

        <span className="px-1 text-[10px] text-muted-foreground">
          {relativeTime(group.groupTimestamp)}
        </span>
      </div>
    </div>
  );
}
