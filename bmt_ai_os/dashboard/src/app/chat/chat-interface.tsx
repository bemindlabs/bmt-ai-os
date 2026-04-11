"use client";

import { useState, useRef, useEffect } from "react";
import { sendChat, type ChatMessage } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Send } from "lucide-react";

interface ChatInterfaceProps {
  models: string[];
}

export function ChatInterface({ models }: ChatInterfaceProps) {
  const defaultModel = models[0] ?? "qwen2.5-coder:7b";
  const [selectedModel, setSelectedModel] = useState(defaultModel);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSend() {
    const text = input.trim();
    if (!text || loading) return;

    const userMsg: ChatMessage = { role: "user", content: text };
    const updated = [...messages, userMsg];
    setMessages(updated);
    setInput("");
    setLoading(true);
    setError(null);

    try {
      const res = await sendChat({
        model: selectedModel,
        messages: updated,
      });

      const assistantMsg = res.choices[0]?.message;
      if (assistantMsg) {
        setMessages((prev) => [...prev, assistantMsg]);
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to reach the controller."
      );
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  return (
    <div className="flex flex-1 flex-col gap-4 min-h-0">
      {/* Model selector */}
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

      {/* Message list */}
      <Card className="flex-1 overflow-hidden">
        <CardContent className="flex h-full flex-col gap-4 overflow-y-auto p-4">
          {messages.length === 0 && (
            <p className="m-auto text-sm text-muted-foreground">
              No messages yet. Start a conversation below.
            </p>
          )}

          {messages.map((msg, i) => (
            <div
              key={i}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[75%] rounded-xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ${
                  msg.role === "user"
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-foreground"
                }`}
              >
                {msg.content}
              </div>
            </div>
          ))}

          {loading && (
            <div className="flex justify-start">
              <div className="rounded-xl bg-muted px-4 py-2.5 text-sm text-muted-foreground">
                Thinking…
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
