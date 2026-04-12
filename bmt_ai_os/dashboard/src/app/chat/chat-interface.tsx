"use client";

import {
  useState,
  useRef,
  useEffect,
  useLayoutEffect,
} from "react";
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
} from "@/lib/sessions";
import {
  filterCommands,
  messagesToMarkdown,
  downloadText,
  type SlashCommand,
} from "@/lib/commands";
import { type AttachedFile } from "@/components/file-drop-zone";
import { Database } from "lucide-react";
import { cn } from "@/lib/utils";
import { MessageGroupRow, groupMessages, type LocalMessage } from "./chat-message";
import { TypingIndicator } from "./typing-indicator";
import { ChatInput } from "./chat-input";
import { useChatSend } from "./use-chat-send";

// ─── Types ────────────────────────────────────────────────────────────────────

interface ChatInterfaceProps {
  models: string[];
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function makeId(): string {
  return Math.random().toString(36).slice(2, 10);
}

const RAG_TOGGLE_KEY = "bmt_rag_enabled";

// ─── Main component ───────────────────────────────────────────────────────────

export function ChatInterface({ models }: ChatInterfaceProps) {
  const defaultModel = models[0] ?? "qwen2.5-coder:7b";

  // ── Core state ──
  const [selectedModel, setSelectedModel] = useState(defaultModel);
  const [messages, setMessages] = useState<LocalMessage[]>([]);
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);

  // ── Session state ──
  const [sessions, setSessions] = useState(() => listSessions());
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
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // ── Derived ──
  const usedTokens = messages.reduce((sum, m) => sum + m.tokens, 0);
  const slashCommands = slashQuery !== null ? filterCommands(slashQuery) : [];

  // ─── Send / streaming logic (extracted hook) ──────────────────────────────

  const { loading, streaming, error: sendError, handleSend, handleStop } = useChatSend({
    messages,
    selectedModel,
    ragEnabled,
    attachments,
    systemPrompt,
    onMessagesChange: (updater) => setMessages(updater),
    onMessagesSet: (msgs) => {
      setMessages(msgs);
      setInput("");
      setAttachments([]);
    },
    onPersist: persistMessages,
  });

  // Merge send error into local error state
  useEffect(() => {
    if (sendError) setError(sendError);
  }, [sendError]);

  // ─── Init: load RAG toggle + sessions from localStorage ───────────────────

  useLayoutEffect(() => {
    const stored = localStorage.getItem(RAG_TOGGLE_KEY);
    if (stored !== null) setRagEnabled(stored === "true");

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

  // ─── Input handlers ───────────────────────────────────────────────────────

  function handleInputChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const val = e.target.value;
    setInput(val);
    if (val.startsWith("/")) {
      const query = val.slice(1);
      if (!query.includes(" ")) {
        setSlashQuery(query);
        setSlashIndex(0);
        return;
      }
    }
    setSlashQuery(null);
  }

  function handleSlashSelect(cmd: SlashCommand) {
    setSlashQuery(null);
    if (cmd.hasArg) {
      setInput(`/${cmd.name} `);
      textareaRef.current?.focus();
    } else {
      executeSlashCommand(cmd, "");
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
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
      void handleSend(input);
    }
  }

  function handleVoiceTranscript(text: string) {
    setInput((prev) => (prev ? `${prev} ${text}` : text));
    textareaRef.current?.focus();
  }

  function handleAttach(files: AttachedFile[]) {
    setAttachments((prev) => [...prev, ...files]);
  }

  function handleRemoveAttachment(id: string) {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  }

  // ─── Render ───────────────────────────────────────────────────────────────

  const groups = groupMessages(messages);
  const isBusy = loading || streaming;

  return (
    <div className="flex h-full min-h-0 flex-1">
      <SessionSidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelect={handleSelectSession}
        onNew={handleNewSession}
        onDelete={handleDeleteSession}
      />

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
        <ChatInput
          input={input}
          isBusy={isBusy}
          attachments={attachments}
          slashQuery={slashQuery}
          slashIndex={slashIndex}
          textareaRef={textareaRef}
          onInputChange={handleInputChange}
          onKeyDown={handleKeyDown}
          onAttach={handleAttach}
          onRemoveAttachment={handleRemoveAttachment}
          onSlashSelect={handleSlashSelect}
          onSlashIndexChange={setSlashIndex}
          onVoiceTranscript={handleVoiceTranscript}
          onSend={() => void handleSend(input)}
          onStop={handleStop}
        />
      </div>
    </div>
  );
}
