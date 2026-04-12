"use client";

import { useCallback, useRef, useState } from "react";
import { streamChat } from "@/lib/api";
import type { ChatMessage } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Sparkles, X, Copy, Check, Replace, Loader2 } from "lucide-react";

// ---------------------------------------------------------------------------
// SSE parser — extracts content deltas from streaming response
// ---------------------------------------------------------------------------

function parseSSEChunk(chunk: string): string {
  let text = "";
  for (const line of chunk.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("data: ")) continue;
    const payload = trimmed.slice(6);
    if (payload === "[DONE]") break;
    try {
      const json = JSON.parse(payload);
      const delta = json.choices?.[0]?.delta?.content;
      if (delta) text += delta;
    } catch {
      // skip malformed chunks
    }
  }
  return text;
}

// ---------------------------------------------------------------------------
// AI Prompt Panel
// ---------------------------------------------------------------------------

interface AiPromptPanelProps {
  filePath: string | null;
  fileContent: string;
  language: string;
  onApply: (code: string) => void;
  onClose: () => void;
}

export function AiPromptPanel({
  filePath,
  fileContent,
  language,
  onApply,
  onClose,
}: AiPromptPanelProps) {
  const [prompt, setPrompt] = useState("");
  const [response, setResponse] = useState("");
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSubmit = useCallback(async () => {
    if (!prompt.trim() || loading) return;

    setLoading(true);
    setResponse("");

    const controller = new AbortController();
    abortRef.current = controller;

    const systemMessage: ChatMessage = {
      role: "system",
      content: [
        "You are a coding assistant integrated into a code editor.",
        "The user is editing a file and wants you to generate or modify code.",
        "Respond ONLY with the code — no markdown fences, no explanations, no preamble.",
        "If the user asks to modify existing code, return the complete modified file content.",
        "If the user asks to generate new code, return just the code.",
        filePath ? `Current file: ${filePath} (${language})` : "",
      ]
        .filter(Boolean)
        .join("\n"),
    };

    const userContent = fileContent.trim()
      ? `Here is the current file content:\n\`\`\`${language}\n${fileContent}\n\`\`\`\n\nInstruction: ${prompt}`
      : prompt;

    const messages: ChatMessage[] = [
      systemMessage,
      { role: "user", content: userContent },
    ];

    try {
      const reader = await streamChat(
        { model: "default", messages },
        controller.signal,
      );

      let accumulated = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const text = parseSSEChunk(value);
        if (text) {
          accumulated += text;
          setResponse(accumulated);
        }
      }
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") {
        // User cancelled
      } else {
        setResponse(
          (prev) => prev + `\n\n[Error: ${err instanceof Error ? err.message : "Request failed"}]`,
        );
      }
    } finally {
      setLoading(false);
      abortRef.current = null;
    }
  }, [prompt, fileContent, filePath, language, loading]);

  const handleCancel = useCallback(() => {
    abortRef.current?.abort();
    setLoading(false);
  }, []);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(response);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [response]);

  const handleApply = useCallback(() => {
    // Strip markdown fences if the model added them despite instructions
    let code = response;
    const fenceMatch = code.match(/^```[\w]*\n([\s\S]*?)\n```$/);
    if (fenceMatch) code = fenceMatch[1];
    onApply(code);
  }, [response, onApply]);

  return (
    <div className="flex h-full flex-col border-l border-border bg-background">
      {/* Header */}
      <div className="flex h-9 shrink-0 items-center justify-between border-b border-border bg-muted/30 px-3">
        <div className="flex items-center gap-1.5">
          <Sparkles className="size-3.5 text-purple-400" />
          <span className="text-xs font-medium">AI Assistant</span>
        </div>
        <button
          onClick={onClose}
          className="rounded p-0.5 text-muted-foreground hover:text-foreground"
          aria-label="Close AI panel"
        >
          <X className="size-3.5" />
        </button>
      </div>

      {/* Prompt input */}
      <div className="border-b border-border p-3">
        <textarea
          ref={textareaRef}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              void handleSubmit();
            }
          }}
          placeholder={
            fileContent.trim()
              ? "Describe the change... (Ctrl+Enter to send)"
              : "Describe what to generate... (Ctrl+Enter to send)"
          }
          className="w-full resize-none rounded border border-input bg-background px-3 py-2 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
          rows={3}
          spellCheck={false}
        />
        <div className="mt-2 flex items-center gap-2">
          <Button
            size="sm"
            onClick={() => void handleSubmit()}
            disabled={!prompt.trim() || loading}
            className="h-7 gap-1.5 text-xs"
          >
            {loading ? (
              <>
                <Loader2 className="size-3 animate-spin" />
                Generating...
              </>
            ) : (
              <>
                <Sparkles className="size-3" />
                Generate
              </>
            )}
          </Button>
          {loading && (
            <Button
              size="sm"
              variant="outline"
              onClick={handleCancel}
              className="h-7 text-xs"
            >
              Cancel
            </Button>
          )}
          {filePath && fileContent.trim() && (
            <span className="ml-auto text-[10px] text-muted-foreground">
              Context: {filePath.split("/").pop()}
            </span>
          )}
        </div>
      </div>

      {/* Response area */}
      <div className="flex min-h-0 flex-1 flex-col">
        {response ? (
          <>
            <div className="flex-1 overflow-auto p-3">
              <pre className="whitespace-pre-wrap font-mono text-xs text-foreground">
                {response}
              </pre>
            </div>
            <div className="flex shrink-0 items-center gap-2 border-t border-border px-3 py-2">
              <Button
                size="sm"
                onClick={handleApply}
                disabled={loading}
                className="h-7 gap-1.5 text-xs"
              >
                <Replace className="size-3" />
                Apply to Editor
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={handleCopy}
                className="h-7 gap-1.5 text-xs"
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
              </Button>
            </div>
          </>
        ) : (
          <div className="flex flex-1 items-center justify-center p-4">
            <p className="text-center text-xs text-muted-foreground">
              {loading
                ? "Generating code..."
                : "Describe what you want to code.\nThe AI will use the current file as context."}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
