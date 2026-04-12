"use client";

import { useState, useRef, useCallback } from "react";
import {
  sendChat,
  streamChat,
  queryRag,
  type ChatMessage,
  type RagSource,
} from "@/lib/api";
import { parseSSEChunk } from "@/lib/sse";
import { estimateTokens } from "@/components/context-meter";
import { attachmentsToContext, type AttachedFile } from "@/components/file-drop-zone";
import type { LocalMessage } from "./chat-message";

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


// ─── Hook ─────────────────────────────────────────────────────────────────────

interface UseChatSendOptions {
  messages: LocalMessage[];
  selectedModel: string;
  ragEnabled: boolean;
  attachments: AttachedFile[];
  systemPrompt: string | null;
  onMessagesChange: (updater: (prev: LocalMessage[]) => LocalMessage[]) => void;
  onMessagesSet: (msgs: LocalMessage[]) => void;
  onPersist: (msgs: LocalMessage[], model: string) => void;
}

interface UseChatSendReturn {
  loading: boolean;
  streaming: boolean;
  error: string | null;
  handleSend: (input: string) => Promise<void>;
  handleStop: () => void;
}

export function useChatSend({
  messages,
  selectedModel,
  ragEnabled,
  attachments,
  systemPrompt,
  onMessagesChange,
  onMessagesSet,
  onPersist,
}: UseChatSendOptions): UseChatSendReturn {
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  function handleStop() {
    abortRef.current?.abort();
    abortRef.current = null;
    setStreaming(false);
    setLoading(false);
  }

  const handleSend = useCallback(
    async (input: string) => {
      const text = input.trim();
      if (!text || loading || streaming) return;

      const attachCtx = attachmentsToContext(attachments);
      const userContent = text + attachCtx;
      const userLocal = toLocalMessage({ role: "user", content: userContent });

      const baseMessages: LocalMessage[] = systemPrompt
        ? [
            toLocalMessage({ role: "system", content: systemPrompt }),
            ...messages,
            userLocal,
          ]
        : [...messages, userLocal];

      onMessagesSet(baseMessages);
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

      const payloadMessages: ChatMessage[] = baseMessages.map((m, idx) => {
        if (idx === baseMessages.length - 1 && ragContext) {
          return { role: m.role, content: m.content + ragContext };
        }
        return { role: m.role, content: m.content };
      });

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const reader = await streamChat(
          { model: selectedModel, messages: payloadMessages },
          controller.signal,
        );

        setLoading(false);
        setStreaming(true);

        const assistantMsg: LocalMessage = {
          id: makeId(),
          role: "assistant",
          content: "",
          timestamp: new Date(),
          tokens: 0,
          sources: ragSources.length > 0 ? ragSources : undefined,
        };

        onMessagesChange((prev) => [...prev, assistantMsg]);

        let accumulated = "";

        // eslint-disable-next-line no-constant-condition
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          if (value) {
            const delta = parseSSEChunk(value);
            if (delta) {
              accumulated += delta;
              onMessagesChange((prev) => {
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

        onMessagesChange((prev) => {
          onPersist(prev, selectedModel);
          return prev;
        });
      } catch (streamErr) {
        if (
          streamErr instanceof Error &&
          (streamErr.name === "AbortError" || controller.signal.aborted)
        ) {
          setStreaming(false);
          setLoading(false);
          abortRef.current = null;
          return;
        }

        try {
          const res = await sendChat({
            model: selectedModel,
            messages: payloadMessages,
          });
          const raw = res.choices[0]?.message;
          if (raw) {
            const assistantLocal = toLocalMessage(
              raw,
              ragSources.length > 0 ? ragSources : undefined,
            );
            onMessagesChange((prev) => {
              const updated = [...prev, assistantLocal];
              onPersist(updated, selectedModel);
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
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [loading, streaming, messages, selectedModel, ragEnabled, attachments, systemPrompt],
  );

  return { loading, streaming, error, handleSend, handleStop };
}
