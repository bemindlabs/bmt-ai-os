"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { streamChat, fetchModels, writeFile, createDirectory } from "@/lib/api";
import type { ChatMessage, OllamaModel } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Sparkles,
  X,
  Copy,
  Check,
  Replace,
  Loader2,
  Settings2,
  FilePlus,
} from "lucide-react";

// ---------------------------------------------------------------------------
// SSE parser
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
      // skip
    }
  }
  return text;
}

// ---------------------------------------------------------------------------
// Storage keys
// ---------------------------------------------------------------------------

const STORAGE_MODEL = "bmt_ai_model";
const STORAGE_TEMP = "bmt_ai_temperature";
const STORAGE_TOKENS = "bmt_ai_max_tokens";

// ---------------------------------------------------------------------------
// AI Prompt Panel
// ---------------------------------------------------------------------------

interface AiPromptPanelProps {
  filePath: string | null;
  fileContent: string;
  language: string;
  onApply: (code: string) => void;
  onClose: () => void;
  /** Prompt history from session (most recent first) */
  promptHistory?: string[];
  /** Callback when a prompt is submitted (to persist to session) */
  onPromptSubmit?: (prompt: string) => void;
  /** Current directory for creating new files */
  currentDir?: string;
  /** Called after a file is created so the tree can refresh */
  onFileCreated?: () => void;
}

export function AiPromptPanel({
  filePath,
  fileContent,
  language,
  onApply,
  onClose,
  promptHistory = [],
  onPromptSubmit,
  currentDir = "",
  onFileCreated,
}: AiPromptPanelProps) {
  const [prompt, setPrompt] = useState("");
  const [response, setResponse] = useState("");
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showSaveAs, setShowSaveAs] = useState(false);
  const [saveAsPath, setSaveAsPath] = useState("");
  const [saveAsStatus, setSaveAsStatus] = useState<"idle" | "saving" | "done" | "error">("idle");
  const abortRef = useRef<AbortController | null>(null);

  // Model selection
  const [models, setModels] = useState<OllamaModel[]>([]);
  const [selectedModel, setSelectedModel] = useState(() =>
    (typeof window !== "undefined" && localStorage.getItem(STORAGE_MODEL)) || "default",
  );
  const [loadingModels, setLoadingModels] = useState(false);

  // Options
  const [showOptions, setShowOptions] = useState(false);
  const [temperature, setTemperature] = useState(() => {
    const stored = typeof window !== "undefined" && localStorage.getItem(STORAGE_TEMP);
    return stored ? parseFloat(stored) : 0.3;
  });
  const [maxTokens, setMaxTokens] = useState(() => {
    const stored = typeof window !== "undefined" && localStorage.getItem(STORAGE_TOKENS);
    return stored ? parseInt(stored, 10) : 4096;
  });

  // Persist settings
  useEffect(() => {
    localStorage.setItem(STORAGE_MODEL, selectedModel);
  }, [selectedModel]);
  useEffect(() => {
    localStorage.setItem(STORAGE_TEMP, String(temperature));
  }, [temperature]);
  useEffect(() => {
    localStorage.setItem(STORAGE_TOKENS, String(maxTokens));
  }, [maxTokens]);

  // Fetch models on mount
  useEffect(() => {
    setLoadingModels(true);
    fetchModels()
      .then((res) => setModels(res.models ?? []))
      .catch(() => setModels([]))
      .finally(() => setLoadingModels(false));
  }, []);

  const handleSubmit = useCallback(async () => {
    if (!prompt.trim() || loading) return;

    setLoading(true);
    setResponse("");
    onPromptSubmit?.(prompt);

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
        "The user can save your output as a new file using the 'Save As' button.",
        filePath ? `Current file: ${filePath} (${language})` : "",
        currentDir ? `Current directory: ${currentDir}` : "",
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
        {
          model: selectedModel,
          messages,
          temperature,
          max_tokens: maxTokens,
        },
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
        // cancelled
      } else {
        setResponse(
          (prev) =>
            prev +
            `\n\n[Error: ${err instanceof Error ? err.message : "Request failed"}]`,
        );
      }
    } finally {
      setLoading(false);
      abortRef.current = null;
    }
  }, [prompt, fileContent, filePath, language, loading, selectedModel, temperature, maxTokens]);

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
    let code = response;
    const fenceMatch = code.match(/^```[\w]*\n([\s\S]*?)\n```$/);
    if (fenceMatch) code = fenceMatch[1];
    onApply(code);
  }, [response, onApply]);

  const handleSaveAs = useCallback(async () => {
    if (!saveAsPath.trim() || !response.trim()) return;
    setSaveAsStatus("saving");
    try {
      let code = response;
      const fenceMatch = code.match(/^```[\w]*\n([\s\S]*?)\n```$/);
      if (fenceMatch) code = fenceMatch[1];

      const fullPath = saveAsPath.startsWith("/")
        ? saveAsPath
        : currentDir
          ? `${currentDir}/${saveAsPath}`
          : saveAsPath;

      await writeFile(fullPath, code);
      setSaveAsStatus("done");
      onFileCreated?.();
      setTimeout(() => {
        setSaveAsStatus("idle");
        setShowSaveAs(false);
      }, 1500);
    } catch {
      setSaveAsStatus("error");
      setTimeout(() => setSaveAsStatus("idle"), 2000);
    }
  }, [saveAsPath, response, currentDir, onFileCreated]);

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

      {/* Model selector + options */}
      <div className="border-b border-border px-3 py-2 space-y-2">
        {/* Model dropdown */}
        <div className="flex items-center gap-2">
          <label className="text-[10px] text-muted-foreground shrink-0 uppercase tracking-wide">
            Model
          </label>
          <select
            value={selectedModel}
            onChange={(e) => setSelectedModel(e.target.value)}
            className="flex-1 h-7 rounded border border-input bg-background px-2 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
            disabled={loading}
          >
            <option value="default">default (auto)</option>
            {models.map((m) => (
              <option key={m.name} value={m.name}>
                {m.name}
              </option>
            ))}
            {loadingModels && <option disabled>Loading models...</option>}
          </select>
          <button
            onClick={() => setShowOptions(!showOptions)}
            className="rounded p-1 text-muted-foreground hover:text-foreground hover:bg-muted"
            title="Model options"
            aria-expanded={showOptions}
          >
            <Settings2 className="size-3.5" />
          </button>
        </div>

        {/* Options panel */}
        {showOptions && (
          <div className="space-y-2 rounded border border-border bg-muted/20 p-2">
            <div className="flex items-center justify-between gap-2">
              <label className="text-[10px] text-muted-foreground">
                Temperature
              </label>
              <div className="flex items-center gap-1.5">
                <input
                  type="range"
                  min={0}
                  max={2}
                  step={0.1}
                  value={temperature}
                  onChange={(e) => setTemperature(parseFloat(e.target.value))}
                  className="w-20 h-1 accent-primary"
                />
                <span className="text-xs font-mono w-7 text-right text-foreground">
                  {temperature.toFixed(1)}
                </span>
              </div>
            </div>
            <div className="flex items-center justify-between gap-2">
              <label className="text-[10px] text-muted-foreground">
                Max tokens
              </label>
              <Input
                type="number"
                min={256}
                max={32768}
                step={256}
                value={maxTokens}
                onChange={(e) => setMaxTokens(parseInt(e.target.value, 10) || 4096)}
                className="h-6 w-20 text-xs font-mono text-right"
              />
            </div>
            <p className="text-[10px] text-muted-foreground">
              Low temperature (0.1-0.3) for precise code. Higher (0.7+) for creative suggestions.
            </p>
          </div>
        )}
      </div>

      {/* Prompt input */}
      <div className="border-b border-border p-3">
        <textarea
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
        {/* Prompt history */}
        {promptHistory.length > 0 && (
          <div className="mt-1.5">
            <select
              onChange={(e) => {
                if (e.target.value) setPrompt(e.target.value);
                e.target.value = "";
              }}
              className="w-full h-6 rounded border border-input bg-background px-1.5 text-[10px] text-muted-foreground focus:outline-none"
              defaultValue=""
            >
              <option value="" disabled>
                Prompt history ({promptHistory.length})...
              </option>
              {promptHistory.map((p, i) => (
                <option key={i} value={p}>
                  {p.length > 60 ? p.slice(0, 60) + "..." : p}
                </option>
              ))}
            </select>
          </div>
        )}

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
              {filePath.split("/").pop()}
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
            <div className="shrink-0 border-t border-border px-3 py-2 space-y-2">
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  onClick={handleApply}
                  disabled={loading}
                  className="h-7 gap-1.5 text-xs"
                >
                  <Replace className="size-3" />
                  Apply
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setShowSaveAs(!showSaveAs);
                    setSaveAsPath(
                      currentDir ? `${currentDir}/new-file.${language === "plaintext" ? "txt" : language}` : "",
                    );
                  }}
                  className="h-7 gap-1.5 text-xs"
                >
                  <FilePlus className="size-3" />
                  Save As
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleCopy}
                  className="h-7 gap-1.5 text-xs"
                >
                  {copied ? (
                    <Check className="size-3" />
                  ) : (
                    <Copy className="size-3" />
                  )}
                </Button>
              </div>

              {/* Save As file path input */}
              {showSaveAs && (
                <div className="flex items-center gap-1.5">
                  <Input
                    value={saveAsPath}
                    onChange={(e) => setSaveAsPath(e.target.value)}
                    placeholder="path/to/new-file.py"
                    className="flex-1 h-7 text-xs font-mono"
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void handleSaveAs();
                      if (e.key === "Escape") setShowSaveAs(false);
                    }}
                    autoFocus
                  />
                  <Button
                    size="sm"
                    onClick={() => void handleSaveAs()}
                    disabled={!saveAsPath.trim() || saveAsStatus === "saving"}
                    className="h-7 text-xs shrink-0"
                  >
                    {saveAsStatus === "saving"
                      ? "Saving..."
                      : saveAsStatus === "done"
                        ? "Created!"
                        : saveAsStatus === "error"
                          ? "Failed"
                          : "Create"}
                  </Button>
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="flex flex-1 items-center justify-center p-4">
            <p className="text-center text-xs text-muted-foreground whitespace-pre-line">
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
