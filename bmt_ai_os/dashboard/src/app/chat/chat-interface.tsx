"use client";

import {
  useState,
  useRef,
  useEffect,
  useCallback,
  useLayoutEffect,
} from "react";
import ReactMarkdown from "react-markdown";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import {
  sendChat,
  streamChat,
  queryRag,
  type ChatMessage,
  type RagSource,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ContextMeter, estimateTokens, TOKEN_BUDGET } from "@/components/context-meter";
import { SessionSidebar } from "@/components/session-sidebar";
import {
  listSessions,
  getSession,
  saveSession,
  createSession,
  deleteSession,
  type Session,
} from "@/lib/sessions";
import { SlashCommandMenu } from "@/components/slash-command-menu";
import {
  filterCommands,
  messagesToMarkdown,
  downloadText,
  type SlashCommand,
} from "@/lib/commands";
import { VoiceInput } from "@/components/voice-input";
import {
  FileDropZone,
  attachmentsToContext,
  usePasteAttach,
  type AttachedFile,
} from "@/components/file-drop-zone";
import { SourceList } from "@/components/source-card";
import {
  Send,
  Bot,
  User,
  Copy,
  Check,
  Square,
  Paperclip,
  Database,
} from "lucide-react";
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
  sources?: RagSource[];
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

function toLocalMessage(
  msg: ChatMessage,
  sources?: RagSource[],
): LocalMessage {
  return {
    ...msg,
    id: makeId(),
    timestamp: new Date(),
    tokens: estimateTokens(msg.content),
    sources,
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

/** Parse incremental SSE text and return accumulated delta content */
function parseSSEChunk(chunk: string): string {
  let delta = "";
  const lines = chunk.split("\n");
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("data:")) continue;
    const payload = trimmed.slice(5).trim();
    if (payload === "[DONE]") continue;
    try {
      const parsed = JSON.parse(payload) as {
        choices?: { delta?: { content?: string } }[];
      };
      const content = parsed.choices?.[0]?.delta?.content;
      if (content) delta += content;
    } catch {
      // Non-JSON SSE line — skip
    }
  }
  return delta;
}

const RAG_TOGGLE_KEY = "bmt_rag_enabled";

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
        h1: ({ children }) => (
          <h1 className="mb-2 text-base font-bold">{children}</h1>
        ),
        h2: ({ children }) => (
          <h2 className="mb-1.5 text-sm font-bold">{children}</h2>
        ),
        h3: ({ children }) => (
          <h3 className="mb-1 text-sm font-semibold">{children}</h3>
        ),
        p: ({ children }) => (
          <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>
        ),
        code: ({ className, children, ...props }) => {
          return (
            <code
              className="rounded bg-black/20 px-1 py-0.5 font-mono text-[0.8em]"
              {...props}
            >
              {children}
            </code>
          );
        },
        pre: ({ children }) => {
          const codeChild =
            children &&
            typeof children === "object" &&
            "props" in (children as React.ReactElement)
              ? (children as React.ReactElement<{
                  className?: string;
                  children?: string;
                }>)
              : null;

          const className = codeChild?.props?.className ?? "";
          const match = /language-(\w+)/.exec(className);
          const lang = match?.[1] ?? "text";
          const codeText = String(codeChild?.props?.children ?? "").replace(
            /\n$/,
            "",
          );

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
        ul: ({ children }) => (
          <ul className="mb-2 ml-4 list-disc space-y-0.5">{children}</ul>
        ),
        ol: ({ children }) => (
          <ol className="mb-2 ml-4 list-decimal space-y-0.5">{children}</ol>
        ),
        li: ({ children }) => <li className="leading-relaxed">{children}</li>,
        blockquote: ({ children }) => (
          <blockquote className="my-1 border-l-2 border-muted-foreground/40 pl-3 text-muted-foreground">
            {children}
          </blockquote>
        ),
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
        hr: () => <hr className="my-3 border-muted" />,
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

// ─── Typing indicator ─────────────────────────────────────────────────────────

function TypingIndicator() {
  return (
    <div className="flex gap-2.5">
      <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <Bot className="size-3.5" aria-hidden="true" />
      </div>
      <div className="rounded-xl bg-muted px-3.5 py-3 text-sm">
        <span className="flex items-center gap-1" aria-label="Thinking">
          <span className="size-1.5 rounded-full bg-current animate-bounce [animation-delay:0ms]" />
          <span className="size-1.5 rounded-full bg-current animate-bounce [animation-delay:150ms]" />
          <span className="size-1.5 rounded-full bg-current animate-bounce [animation-delay:300ms]" />
        </span>
      </div>
    </div>
  );
}

// ─── Message group row ────────────────────────────────────────────────────────

interface MessageGroupRowProps {
  group: MessageGroup;
}

function MessageGroupRow({ group }: MessageGroupRowProps) {
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

// ─── Main component ───────────────────────────────────────────────────────────

export function ChatInterface({ models }: ChatInterfaceProps) {
  const defaultModel = models[0] ?? "qwen2.5-coder:7b";

  // ── Core state ──
  const [selectedModel, setSelectedModel] = useState(defaultModel);
  const [messages, setMessages] = useState<LocalMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ── Session state ──
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);

  // ── Slash command state ──
  const [slashQuery, setSlashQuery] = useState<string | null>(null);
  const [slashIndex, setSlashIndex] = useState(0);

  // ── Voice + attachment state ──
  const [attachments, setAttachments] = useState<AttachedFile[]>([]);

  // ── RAG state ──
  const [ragEnabled, setRagEnabled] = useState(false);

  // ── System prompt ──
  const [systemPrompt, setSystemPrompt] = useState<string | null>(null);

  // ── Refs ──
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // ── Derived ──
  const usedTokens = messages.reduce((sum, m) => sum + m.tokens, 0);
  const slashCommands = slashQuery !== null ? filterCommands(slashQuery) : [];

  // ─── Init: load RAG toggle + sessions from localStorage ───────────────────

  useLayoutEffect(() => {
    // RAG toggle persisted preference
    const stored = localStorage.getItem(RAG_TOGGLE_KEY);
    if (stored !== null) setRagEnabled(stored === "true");

    // Load sessions and restore most recent
    const all = listSessions();
    setSessions(all);
    if (all.length > 0) {
      const mostRecent = all[0];
      setActiveSessionId(mostRecent.id);
      setSelectedModel(mostRecent.model || defaultModel);
      setMessages(
        mostRecent.messages.map((m) => ({
          ...m,
          id: makeId(),
          timestamp: new Date(),
          tokens: estimateTokens(m.content),
        })),
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ─── Scroll to bottom on new messages ────────────────────────────────────

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading, streaming]);

  // ─── Persist RAG toggle ───────────────────────────────────────────────────

  function toggleRag() {
    const next = !ragEnabled;
    setRagEnabled(next);
    localStorage.setItem(RAG_TOGGLE_KEY, String(next));
  }

  // ─── Session management ───────────────────────────────────────────────────

  function refreshSessions() {
    setSessions(listSessions());
  }

  function handleNewSession() {
    const session = createSession(selectedModel);
    setActiveSessionId(session.id);
    setMessages([]);
    setError(null);
    setSystemPrompt(null);
    refreshSessions();
  }

  function handleSelectSession(id: string) {
    const session = getSession(id);
    if (!session) return;
    setActiveSessionId(id);
    setSelectedModel(session.model || defaultModel);
    setMessages(
      session.messages.map((m) => ({
        ...m,
        id: makeId(),
        timestamp: new Date(),
        tokens: estimateTokens(m.content),
      })),
    );
    setError(null);
  }

  function handleDeleteSession(id: string) {
    deleteSession(id);
    if (activeSessionId === id) {
      const remaining = listSessions();
      if (remaining.length > 0) {
        handleSelectSession(remaining[0].id);
      } else {
        setActiveSessionId(null);
        setMessages([]);
        setError(null);
      }
    }
    refreshSessions();
  }

  function persistMessages(msgs: LocalMessage[], model?: string) {
    let sid = activeSessionId;
    if (!sid) {
      const session = createSession(model ?? selectedModel);
      sid = session.id;
      setActiveSessionId(sid);
    }
    saveSession(
      sid,
      msgs.map(({ role, content }) => ({ role, content })),
      model ?? selectedModel,
    );
    refreshSessions();
  }

  // ─── Stop streaming ───────────────────────────────────────────────────────

  function handleStop() {
    abortRef.current?.abort();
    abortRef.current = null;
    setStreaming(false);
    setLoading(false);
  }

  // ─── Slash command execution ──────────────────────────────────────────────

  function executeSlashCommand(cmd: SlashCommand, arg: string) {
    switch (cmd.name) {
      case "clear":
        setMessages([]);
        setError(null);
        setSystemPrompt(null);
        break;

      case "model": {
        const target = arg.trim();
        if (target) setSelectedModel(target);
        break;
      }

      case "rag":
        toggleRag();
        break;

      case "export": {
        const md = messagesToMarkdown(
          messages.map(({ role, content }) => ({ role, content })),
        );
        downloadText("conversation.md", md);
        break;
      }

      case "system": {
        const prompt = arg.trim();
        if (prompt) setSystemPrompt(prompt);
        break;
      }
    }
    setInput("");
    setSlashQuery(null);
  }

  // ─── Handle input change ──────────────────────────────────────────────────

  function handleInputChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const val = e.target.value;
    setInput(val);

    // Detect slash command prefix
    if (val.startsWith("/")) {
      const query = val.slice(1); // everything after the slash
      // Only show menu while no space yet (still typing command name)
      if (!query.includes(" ")) {
        setSlashQuery(query);
        setSlashIndex(0);
        return;
      }
    }
    setSlashQuery(null);
  }

  // ─── Slash command menu selection ─────────────────────────────────────────

  function handleSlashSelect(cmd: SlashCommand) {
    setSlashQuery(null);
    if (cmd.hasArg) {
      // Pre-fill the command name and let user type the arg
      setInput(`/${cmd.name} `);
      textareaRef.current?.focus();
    } else {
      executeSlashCommand(cmd, "");
    }
  }

  // ─── Keyboard handler ─────────────────────────────────────────────────────

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Slash command menu navigation
    if (slashQuery !== null && slashCommands.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSlashIndex((i) => (i + 1) % slashCommands.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSlashIndex((i) => (i - 1 + slashCommands.length) % slashCommands.length);
        return;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        handleSlashSelect(slashCommands[slashIndex]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setSlashQuery(null);
        return;
      }
    }

    if (e.key === "Enter" && !e.shiftKey) {
      // Check if input is a completed slash command (no hasArg, or has space already)
      if (input.startsWith("/")) {
        const parts = input.slice(1).split(" ");
        const cmdName = parts[0];
        const arg = parts.slice(1).join(" ");
        const matched = slashCommands.find((c) => c.name === cmdName);
        if (matched && (!matched.hasArg || arg)) {
          e.preventDefault();
          executeSlashCommand(matched, arg);
          return;
        }
      }
      e.preventDefault();
      void handleSend();
    }
  }

  // ─── Voice transcript ─────────────────────────────────────────────────────

  function handleVoiceTranscript(text: string) {
    setInput((prev) => (prev ? `${prev} ${text}` : text));
    textareaRef.current?.focus();
  }

  // ─── Attachment handlers ──────────────────────────────────────────────────

  function handleAttach(files: AttachedFile[]) {
    setAttachments((prev) => [...prev, ...files]);
  }

  function handleRemoveAttachment(id: string) {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  }

  const handlePaste = usePasteAttach(handleAttach);

  function handlePaperclipClick() {
    fileInputRef.current?.click();
  }

  function handleFileInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    if (e.target.files && e.target.files.length > 0) {
      const built: AttachedFile[] = Array.from(e.target.files).map((f) => ({
        id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
        file: f,
        previewUrl: f.type.startsWith("image/")
          ? URL.createObjectURL(f)
          : null,
        isImage: f.type.startsWith("image/"),
      }));
      handleAttach(built);
      e.target.value = "";
    }
  }

  // ─── Main send handler ────────────────────────────────────────────────────

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || loading || streaming) return;

    // Build user content (append attachment context)
    const attachCtx = attachmentsToContext(attachments);
    const userContent = text + attachCtx;

    const userLocal = toLocalMessage({ role: "user", content: userContent });

    // Build the messages array to send (include optional system prompt)
    const baseMessages: LocalMessage[] = systemPrompt
      ? [
          toLocalMessage({ role: "system", content: systemPrompt }),
          ...messages,
          userLocal,
        ]
      : [...messages, userLocal];

    setMessages(baseMessages);
    setInput("");
    setAttachments([]);
    setLoading(true);
    setError(null);

    // ── RAG: query before sending ──
    let ragSources: RagSource[] = [];
    let ragContext = "";
    if (ragEnabled) {
      try {
        const ragRes = await queryRag({ question: text, top_k: 5 });
        ragSources = ragRes.sources;
        if (ragRes.answer) {
          ragContext = `\n\n[Relevant context from documents]\n${ragRes.answer}`;
        }
      } catch {
        // RAG failure is non-fatal — continue without context
      }
    }

    // Build the payload messages (inject RAG context into last user message)
    const payloadMessages: ChatMessage[] = baseMessages.map((m, idx) => {
      if (idx === baseMessages.length - 1 && ragContext) {
        return { role: m.role, content: m.content + ragContext };
      }
      return { role: m.role, content: m.content };
    });

    // ── Try SSE streaming first ──
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const reader = await streamChat(
        { model: selectedModel, messages: payloadMessages },
        controller.signal,
      );

      setLoading(false);
      setStreaming(true);

      // Add placeholder assistant message
      const assistantMsg: LocalMessage = {
        id: makeId(),
        role: "assistant",
        content: "",
        timestamp: new Date(),
        tokens: 0,
        sources: ragSources.length > 0 ? ragSources : undefined,
      };

      setMessages((prev) => [...prev, assistantMsg]);

      let accumulated = "";

      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        if (value) {
          const delta = parseSSEChunk(value);
          if (delta) {
            accumulated += delta;
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last && last.role === "assistant") {
                updated[updated.length - 1] = {
                  ...last,
                  content: accumulated,
                  tokens: estimateTokens(accumulated),
                };
              }
              return updated;
            });
          }
        }
      }

      setMessages((prev) => {
        persistMessages(prev, selectedModel);
        return prev;
      });
    } catch (streamErr) {
      // Abort is intentional — do not fall back
      if (
        streamErr instanceof Error &&
        (streamErr.name === "AbortError" || controller.signal.aborted)
      ) {
        setStreaming(false);
        setLoading(false);
        abortRef.current = null;
        return;
      }

      // Stream failed — fall back to non-streaming
      try {
        const res = await sendChat({
          model: selectedModel,
          messages: payloadMessages,
        });
        const raw = res.choices[0]?.message;
        if (raw) {
          const assistantLocal = toLocalMessage(raw, ragSources.length > 0 ? ragSources : undefined);
          setMessages((prev) => {
            const updated = [...prev, assistantLocal];
            persistMessages(updated, selectedModel);
            return updated;
          });
        }
      } catch (fallbackErr) {
        setError(
          fallbackErr instanceof Error
            ? fallbackErr.message
            : "Failed to reach the controller.",
        );
      }
    } finally {
      setStreaming(false);
      setLoading(false);
      abortRef.current = null;
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    input,
    loading,
    streaming,
    messages,
    selectedModel,
    ragEnabled,
    attachments,
    systemPrompt,
    activeSessionId,
  ]);

  const groups = groupMessages(messages);
  const isBusy = loading || streaming;

  return (
    <div className="flex h-full min-h-0 flex-1">
      {/* Session Sidebar (BMTOS-102) */}
      <SessionSidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelect={handleSelectSession}
        onNew={handleNewSession}
        onDelete={handleDeleteSession}
      />

      {/* Main chat area */}
      <div className="flex flex-1 flex-col gap-3 min-h-0 p-4">
        {/* Header row: model selector + RAG toggle + clear */}
        <div className="flex items-center gap-2 flex-wrap">
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
            disabled={isBusy}
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

          {/* RAG toggle (BMTOS-105) */}
          <button
            type="button"
            onClick={toggleRag}
            aria-pressed={ragEnabled}
            title={ragEnabled ? "RAG enabled — click to disable" : "RAG disabled — click to enable"}
            className={cn(
              "flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
              ragEnabled
                ? "border-emerald-500 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                : "border-input bg-background text-muted-foreground hover:text-foreground",
            )}
          >
            <Database className="size-3.5" />
            RAG
            <span
              className={cn(
                "ml-0.5 size-2 rounded-full",
                ragEnabled ? "bg-emerald-500" : "bg-muted-foreground/40",
              )}
              aria-hidden="true"
            />
          </button>

          {messages.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setMessages([]);
                setError(null);
              }}
              disabled={isBusy}
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

            {loading && !streaming && <TypingIndicator />}

            {error && (
              <p className="text-center text-xs text-destructive">{error}</p>
            )}

            <div ref={bottomRef} />
          </CardContent>
        </Card>

        {/* Input area */}
        <div className="flex flex-col gap-2">
          {/* Slash command menu (BMTOS-103) */}
          <div className="relative">
            {slashQuery !== null && slashCommands.length > 0 && (
              <SlashCommandMenu
                commands={slashCommands}
                activeIndex={slashIndex}
                onSelect={handleSlashSelect}
                onActiveIndexChange={setSlashIndex}
              />
            )}

            {/* FileDropZone wraps the textarea (BMTOS-104) */}
            <FileDropZone
              attachments={attachments}
              onAttach={handleAttach}
              onRemove={handleRemoveAttachment}
            >
              <textarea
                ref={textareaRef}
                value={input}
                onChange={handleInputChange}
                onKeyDown={handleKeyDown}
                onPaste={handlePaste}
                placeholder="Type a message or /command… (Enter to send, Shift+Enter for newline)"
                rows={2}
                disabled={isBusy}
                className="w-full resize-none rounded-lg border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring/50 disabled:opacity-50"
              />
            </FileDropZone>
          </div>

          {/* Action row */}
          <div className="flex items-center gap-2 justify-end">
            {/* Hidden file input (BMTOS-104) */}
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="hidden"
              onChange={handleFileInputChange}
              aria-hidden="true"
            />

            {/* Paperclip button */}
            <Button
              type="button"
              variant="outline"
              size="icon"
              onClick={handlePaperclipClick}
              disabled={isBusy}
              aria-label="Attach file"
              title="Attach file"
            >
              <Paperclip className="size-4" />
            </Button>

            {/* Voice input (BMTOS-104) */}
            <VoiceInput
              onTranscript={handleVoiceTranscript}
              disabled={isBusy}
            />

            {/* Stop / Send button */}
            {isBusy ? (
              <Button
                type="button"
                variant="destructive"
                size="icon"
                onClick={handleStop}
                aria-label="Stop generation"
                title="Stop generation"
              >
                <Square className="size-4 fill-current" />
              </Button>
            ) : (
              <Button
                onClick={() => void handleSend()}
                disabled={!input.trim() && attachments.length === 0}
                size="icon"
                aria-label="Send message"
              >
                <Send className="size-4" />
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
