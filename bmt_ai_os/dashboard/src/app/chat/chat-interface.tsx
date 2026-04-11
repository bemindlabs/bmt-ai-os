"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { sendChat, type ChatMessage } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ContextMeter, estimateTokens, TOKEN_BUDGET } from "@/components/context-meter";
import { Send, Bot, User, Copy, Check } from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────────────

interface ChatInterfaceProps {
  models: string[];
}

/** ChatMessage extended with local metadata */
interface LocalMessage extends ChatMessage {
  id: string;
  timestamp: Date;
  tokens: number;
}

/** A consecutive run of messages from the same role */
interface MessageGroup {
  role: "user" | "assistant" | "system";
  messages: LocalMessage[];
  groupTimestamp: Date;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function makeId(): string {
  return Math.random().toString(36).slice(2, 10);
}

function toLocalMessage(msg: ChatMessage): LocalMessage {
  return {
    ...msg,
    id: makeId(),
    timestamp: new Date(),
    tokens: estimateTokens(msg.content),
  };
}

/** Group consecutive same-role messages */
function groupMessages(messages: LocalMessage[]): MessageGroup[] {
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

// ─── Sub-components ───────────────────────────────────────────────────────────

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

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard API unavailable — silently fail
    }
  }

  return (
    <button
      onClick={handleCopy}
      className="absolute right-2 top-2 flex items-center gap-1 rounded bg-zinc-700 px-1.5 py-0.5 text-xs text-zinc-200 opacity-0 transition-opacity group-hover/code:opacity-100 hover:bg-zinc-600"
      aria-label="Copy code"
      type="button"
    >
      {copied ? (
        <>
          <Check className="size-3" />
          Copied
        </>
      ) : (
        <>
          <Copy className="size-3" />
          Copy
        </>
      )}
    </button>
  );
}

interface MarkdownContentProps {
  content: string;
}

function MarkdownContent({ content }: MarkdownContentProps) {
  return (
    <ReactMarkdown
      components={{
        // Headings
        h1: ({ children }) => (
          <h1 className="mb-2 text-base font-bold">{children}</h1>
        ),
        h2: ({ children }) => (
          <h2 className="mb-1.5 text-sm font-bold">{children}</h2>
        ),
        h3: ({ children }) => (
          <h3 className="mb-1 text-sm font-semibold">{children}</h3>
        ),
        // Paragraphs
        p: ({ children }) => (
          <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>
        ),
        // Inline code
        code: ({ className, children, ...props }) => {
          const match = /language-(\w+)/.exec(className ?? "");
          const lang = match?.[1];
          // Block code — rendered by the pre handler below via the node check
          // Inline code
          return (
            <code
              className="rounded bg-black/20 px-1 py-0.5 font-mono text-[0.8em]"
              {...props}
            >
              {children}
            </code>
          );
        },
        // Code blocks (fenced)
        pre: ({ children, ...props }) => {
          // Extract code content and language from the nested <code> child
          const codeChild =
            children &&
            typeof children === "object" &&
            "props" in (children as React.ReactElement)
              ? (children as React.ReactElement<{ className?: string; children?: string }>)
              : null;

          const className = codeChild?.props?.className ?? "";
          const match = /language-(\w+)/.exec(className);
          const lang = match?.[1] ?? "text";
          const codeText = String(codeChild?.props?.children ?? "").replace(/\n$/, "");

          return (
            <div className="group/code relative my-2 overflow-hidden rounded-lg text-xs">
              <CopyButton text={codeText} />
              <SyntaxHighlighter
                style={oneDark}
                language={lang}
                PreTag="div"
                customStyle={{
                  margin: 0,
                  borderRadius: "0.5rem",
                  fontSize: "0.75rem",
                  padding: "0.75rem 1rem",
                }}
              >
                {codeText}
              </SyntaxHighlighter>
            </div>
          );
        },
        // Lists
        ul: ({ children }) => (
          <ul className="mb-2 ml-4 list-disc space-y-0.5">{children}</ul>
        ),
        ol: ({ children }) => (
          <ol className="mb-2 ml-4 list-decimal space-y-0.5">{children}</ol>
        ),
        li: ({ children }) => <li className="leading-relaxed">{children}</li>,
        // Blockquote
        blockquote: ({ children }) => (
          <blockquote className="my-1 border-l-2 border-muted-foreground/40 pl-3 text-muted-foreground">
            {children}
          </blockquote>
        ),
        // Links
        a: ({ href, children }) => (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="underline decoration-dotted hover:decoration-solid"
          >
            {children}
          </a>
        ),
        // Horizontal rule
        hr: () => <hr className="my-3 border-muted" />,
        // Strong / em
        strong: ({ children }) => (
          <strong className="font-semibold">{children}</strong>
        ),
        em: ({ children }) => <em className="italic">{children}</em>,
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

// ─── Message group row ────────────────────────────────────────────────────────

interface MessageGroupRowProps {
  group: MessageGroup;
}

function MessageGroupRow({ group }: MessageGroupRowProps) {
  const isUser = group.role === "user";
  const [tick, setTick] = useState(0);

  // Refresh relative timestamps every 30 s
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 30_000);
    return () => clearInterval(id);
  }, []);

  return (
    <div
      className={cn(
        "flex gap-2.5",
        isUser ? "flex-row-reverse" : "flex-row"
      )}
    >
      {/* Avatar */}
      <div
        className={cn(
          "mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full text-xs",
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-muted text-muted-foreground"
        )}
        aria-hidden="true"
      >
        {isUser ? <User className="size-3.5" /> : <Bot className="size-3.5" />}
      </div>

      {/* Bubble stack */}
      <div
        className={cn(
          "flex max-w-[75%] flex-col gap-1",
          isUser ? "items-end" : "items-start"
        )}
      >
        {group.messages.map((msg, idx) => (
          <div
            key={msg.id}
            className={cn(
              "rounded-xl px-3.5 py-2.5 text-sm leading-relaxed",
              isUser
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-foreground"
            )}
          >
            {isUser ? (
              <span className="whitespace-pre-wrap">{msg.content}</span>
            ) : (
              <MarkdownContent content={msg.content} />
            )}
            <TokenBadge tokens={msg.tokens} />
          </div>
        ))}

        {/* Group timestamp */}
        <span className="px-1 text-[10px] text-muted-foreground">
          {relativeTime(group.groupTimestamp)}
        </span>
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function ChatInterface({ models }: ChatInterfaceProps) {
  const defaultModel = models[0] ?? "qwen2.5-coder:7b";
  const [selectedModel, setSelectedModel] = useState(defaultModel);
  const [messages, setMessages] = useState<LocalMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Total used tokens across all messages
  const usedTokens = messages.reduce((sum, m) => sum + m.tokens, 0);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || loading) return;

    const userLocal = toLocalMessage({ role: "user", content: text });
    const updated = [...messages, userLocal];
    setMessages(updated);
    setInput("");
    setLoading(true);
    setError(null);

    try {
      const res = await sendChat({
        model: selectedModel,
        messages: updated.map(({ role, content }) => ({ role, content })),
      });

      const raw = res.choices[0]?.message;
      if (raw) {
        setMessages((prev) => [...prev, toLocalMessage(raw)]);
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to reach the controller."
      );
    } finally {
      setLoading(false);
    }
  }, [input, loading, messages, selectedModel]);

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  const groups = groupMessages(messages);

  return (
    <div className="flex flex-1 flex-col gap-3 min-h-0">
      {/* Model selector row */}
      <div className="flex items-center gap-2">
        <label
          htmlFor="model-select"
          className="text-sm font-medium text-muted-foreground"
        >
          Model
        </label>
        <select
          id="model-select"
          value={selectedModel}
          onChange={(e) => setSelectedModel(e.target.value)}
          className="h-8 rounded-lg border border-input bg-background px-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring/50"
          disabled={loading}
        >
          {models.length > 0 ? (
            models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))
          ) : (
            <option value={defaultModel}>{defaultModel}</option>
          )}
        </select>
        {messages.length > 0 && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setMessages([]);
              setError(null);
            }}
            disabled={loading}
          >
            Clear
          </Button>
        )}
      </div>

      {/* Context meter */}
      {messages.length > 0 && (
        <ContextMeter
          usedTokens={usedTokens}
          budgetTokens={TOKEN_BUDGET}
          className="px-1"
        />
      )}

      {/* Message list */}
      <Card className="flex-1 overflow-hidden">
        <CardContent className="flex h-full flex-col gap-4 overflow-y-auto p-4">
          {messages.length === 0 && (
            <p className="m-auto text-sm text-muted-foreground">
              No messages yet. Start a conversation below.
            </p>
          )}

          {groups.map((group, i) => (
            <MessageGroupRow key={i} group={group} />
          ))}

          {loading && (
            <div className="flex gap-2.5">
              <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
                <Bot className="size-3.5" aria-hidden="true" />
              </div>
              <div className="rounded-xl bg-muted px-3.5 py-2.5 text-sm text-muted-foreground">
                <span className="animate-pulse">Thinking…</span>
              </div>
            </div>
          )}

          {error && (
            <p className="text-center text-xs text-destructive">{error}</p>
          )}

          <div ref={bottomRef} />
        </CardContent>
      </Card>

      {/* Input bar */}
      <div className="flex items-end gap-2">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type a message… (Enter to send, Shift+Enter for newline)"
          rows={2}
          disabled={loading}
          className="flex-1 resize-none rounded-lg border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring/50 disabled:opacity-50"
        />
        <Button
          onClick={handleSend}
          disabled={loading || !input.trim()}
          size="icon"
          aria-label="Send message"
        >
          <Send className="size-4" />
        </Button>
      </div>
    </div>
  );
}
