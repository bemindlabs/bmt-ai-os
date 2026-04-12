"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  streamChat,
  streamChatWithTools,
  fetchProviders,
  fetchProviderModels,
  fetchProviderKeys,
} from "@/lib/api";
import type { ChatMessage, Provider, ToolCallSummary } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Sparkles,
  X,
  Loader2,
  FolderEdit,
  GitCompare,
  Wrench,
} from "lucide-react";
import { ProviderKeySetup } from "./provider-key-setup";
import { AiProviderSelector, isCloudProvider, providerLabel } from "./ai-provider-selector";
import { AiOptionsPanel } from "./ai-options-panel";
import { AiPromptInput } from "./ai-prompt-input";
import { AiResponseArea } from "./ai-response-area";
import { HealthDot } from "./ai-provider-selector";
import { parseMultiFileResponse } from "./multi-file-edit";
import type { EditorSlashCommand } from "./slash-commands";

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
const STORAGE_PROVIDER = "bmt_ai_provider";
const STORAGE_TEMP = "bmt_ai_temperature";
const STORAGE_TOKENS = "bmt_ai_max_tokens";

// ---------------------------------------------------------------------------
// Props
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

// ---------------------------------------------------------------------------
// AiPromptPanel — orchestrator
// ---------------------------------------------------------------------------

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
  // Core prompt / response state
  const [prompt, setPrompt] = useState("");
  const [response, setResponse] = useState("");
  const [loading, setLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // UI mode state
  const [showDiff, setShowDiff] = useState(false);
  const [compareMode, setCompareMode] = useState(false);
  const [multiFileMode, setMultiFileMode] = useState(false);
  const [showOptions, setShowOptions] = useState(false);
  const [showKeySetup, setShowKeySetup] = useState(false);

  // Tool-use mode
  const [toolsEnabled, setToolsEnabled] = useState(
    () => typeof window !== "undefined" && localStorage.getItem("bmt_ai_tools_enabled") === "1",
  );
  const [toolCallLog, setToolCallLog] = useState<ToolCallSummary[]>([]);

  // Slash command active state
  const [activeCommand, setActiveCommand] = useState<EditorSlashCommand | null>(null);

  // Provider / model state
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loadingProviders, setLoadingProviders] = useState(false);
  const [providerModels, setProviderModels] = useState<Record<string, string[]>>({});
  const [loadingModels, setLoadingModels] = useState(false);
  const [keyedProviders, setKeyedProviders] = useState<Set<string>>(new Set());
  const [loadingKeys, setLoadingKeys] = useState(false);

  const [selectedProvider, setSelectedProvider] = useState<string>(
    () => (typeof window !== "undefined" && localStorage.getItem(STORAGE_PROVIDER)) || "default",
  );
  const [selectedModel, setSelectedModel] = useState<string>(
    () => (typeof window !== "undefined" && localStorage.getItem(STORAGE_MODEL)) || "default",
  );

  // Options
  const [temperature, setTemperature] = useState(() => {
    const stored = typeof window !== "undefined" && localStorage.getItem(STORAGE_TEMP);
    return stored ? parseFloat(stored) : 0.3;
  });
  const [maxTokens, setMaxTokens] = useState(() => {
    const stored = typeof window !== "undefined" && localStorage.getItem(STORAGE_TOKENS);
    return stored ? parseInt(stored, 10) : 4096;
  });

  // ---------------------------------------------------------------------------
  // Persist settings
  // ---------------------------------------------------------------------------

  useEffect(() => { localStorage.setItem(STORAGE_PROVIDER, selectedProvider); }, [selectedProvider]);
  useEffect(() => { localStorage.setItem(STORAGE_MODEL, selectedModel); }, [selectedModel]);
  useEffect(() => { localStorage.setItem(STORAGE_TEMP, String(temperature)); }, [temperature]);
  useEffect(() => { localStorage.setItem(STORAGE_TOKENS, String(maxTokens)); }, [maxTokens]);

  // ---------------------------------------------------------------------------
  // Fetch providers on mount
  // ---------------------------------------------------------------------------

  useEffect(() => {
    setLoadingProviders(true);
    fetchProviders()
      .then((res) => setProviders(res.providers ?? []))
      .catch(() => setProviders([]))
      .finally(() => setLoadingProviders(false));
  }, []);

  // ---------------------------------------------------------------------------
  // Fetch API key status for all cloud providers once providers load
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (providers.length === 0) return;
    const cloudProviders = providers.filter((p) => isCloudProvider(p.name));
    if (cloudProviders.length === 0) return;

    setLoadingKeys(true);
    Promise.allSettled(
      cloudProviders.map((p) =>
        fetchProviderKeys(p.name).then((res) => ({
          name: p.name,
          hasKey: (res.keys ?? []).some((k) => k.status === "active"),
        })),
      ),
    )
      .then((results) => {
        const keyed = new Set<string>();
        for (const r of results) {
          if (r.status === "fulfilled" && r.value.hasKey) keyed.add(r.value.name);
        }
        setKeyedProviders(keyed);
      })
      .finally(() => setLoadingKeys(false));
  }, [providers]);

  // ---------------------------------------------------------------------------
  // Fetch models for all providers once provider list loads
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (providers.length === 0) return;
    setLoadingModels(true);
    fetchProviderModels("all")
      .then((res) => {
        const allIds = (res.models ?? [])
          .map((m) => m.id ?? (m as { name?: string }).name ?? "")
          .filter(Boolean);
        const byProvider: Record<string, string[]> = {};
        for (const p of providers) {
          const prefixed = allIds.filter((id) =>
            id.toLowerCase().startsWith(p.name.toLowerCase() + "/"),
          );
          byProvider[p.name] = prefixed.length > 0 ? prefixed : allIds;
        }
        setProviderModels(byProvider);
      })
      .catch(() => setProviderModels({}))
      .finally(() => setLoadingModels(false));
  }, [providers]);

  // ---------------------------------------------------------------------------
  // Provider selection handler
  // ---------------------------------------------------------------------------

  const handleProviderSelect = useCallback(
    (name: string) => {
      setSelectedProvider(name);
      setShowKeySetup(false);
      if (name === "default") {
        setSelectedModel("default");
        return;
      }
      const models = providerModels[name] ?? [];
      setSelectedModel(models[0] ?? "default");
      if (isCloudProvider(name) && !keyedProviders.has(name) && !loadingKeys) {
        setShowKeySetup(true);
      }
    },
    [providerModels, keyedProviders, loadingKeys],
  );

  // ---------------------------------------------------------------------------
  // After successful key save: refresh key status
  // ---------------------------------------------------------------------------

  const handleProviderKeySaved = useCallback(() => {
    if (!selectedProvider || selectedProvider === "default") return;
    fetchProviderKeys(selectedProvider)
      .then((res) => {
        const hasKey = (res.keys ?? []).some((k) => k.status === "active");
        if (hasKey) setKeyedProviders((prev) => new Set([...prev, selectedProvider]));
      })
      .catch(() => null)
      .finally(() => setShowKeySetup(false));
  }, [selectedProvider]);

  // ---------------------------------------------------------------------------
  // Slash command selection — replaces trigger text + sets active command
  // ---------------------------------------------------------------------------

  const handleCommandSelect = useCallback((cmd: EditorSlashCommand) => {
    setActiveCommand(cmd);
    setPrompt((prev) => {
      const replaced = prev.replace(/(^|\n)\/([\w]*)$/, "$1");
      return replaced + cmd.description;
    });
  }, []);

  // ---------------------------------------------------------------------------
  // Code extraction helper (strip markdown fences)
  // ---------------------------------------------------------------------------

  const extractCode = useCallback((raw: string): string => {
    const fenceMatch = raw.match(/^```[\w]*\n([\s\S]*?)\n```$/);
    return fenceMatch ? fenceMatch[1] : raw;
  }, []);

  // ---------------------------------------------------------------------------
  // Submit handler
  // ---------------------------------------------------------------------------

  const handleSubmit = useCallback(async () => {
    if (!prompt.trim() || loading) return;

    setLoading(true);
    setResponse("");
    setShowDiff(false);
    onPromptSubmit?.(prompt);

    const MULTI_FILE_SYSTEM_PROMPT = [
      "When creating or editing multiple files, use this format for each file:",
      "",
      "### FILE: path/to/file.ext",
      "```language",
      "file content here",
      "```",
      "",
      "Include the complete file content for each file. List all files that need to be created or modified.",
    ].join("\n");

    const controller = new AbortController();
    abortRef.current = controller;

    const defaultSystemContent = [
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
      .join("\n");

    const multiFileSystemContent = [
      "You are a coding assistant integrated into a code editor.",
      MULTI_FILE_SYSTEM_PROMPT,
      filePath ? `Current file: ${filePath} (${language})` : "",
      currentDir ? `Current directory: ${currentDir}` : "",
    ]
      .filter(Boolean)
      .join("\n");

    const systemMessage: ChatMessage = {
      role: "system",
      content: activeCommand
        ? [
            activeCommand.systemPrompt,
            filePath ? `Current file: ${filePath} (${language})` : "",
            currentDir ? `Current directory: ${currentDir}` : "",
          ]
            .filter(Boolean)
            .join("\n")
        : multiFileMode
          ? multiFileSystemContent
          : defaultSystemContent,
    };

    const userContent = fileContent.trim()
      ? `Here is the current file content:\n\`\`\`${language}\n${fileContent}\n\`\`\`\n\nInstruction: ${prompt}`
      : prompt;

    const messages: ChatMessage[] = [
      systemMessage,
      { role: "user", content: userContent },
    ];

    let modelArg = selectedModel;
    if (selectedProvider !== "default") {
      if (!selectedModel || selectedModel === "default") {
        modelArg = selectedProvider;
      } else if (!selectedModel.toLowerCase().startsWith(selectedProvider.toLowerCase() + "/")) {
        modelArg = `${selectedProvider}/${selectedModel}`;
      }
    }

    try {
      const chatReq = { model: modelArg, messages, temperature, max_tokens: maxTokens };

      let reader: ReadableStreamDefaultReader<string>;
      if (toolsEnabled) {
        setToolCallLog([]);
        const result = await streamChatWithTools(chatReq, controller.signal);
        reader = result.reader;
        if (result.toolCalls.length > 0) setToolCallLog(result.toolCalls);
      } else {
        reader = await streamChat(chatReq, controller.signal);
      }

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
      if (!multiFileMode) {
        const parsed = parseMultiFileResponse(accumulated);
        if (parsed.length >= 2) setMultiFileMode(true);
      }
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") {
        // cancelled
      } else {
        setResponse(
          (prev) =>
            prev + `\n\n[Error: ${err instanceof Error ? err.message : "Request failed"}]`,
        );
      }
    } finally {
      setLoading(false);
      abortRef.current = null;
    }
  }, [prompt, fileContent, filePath, language, loading, selectedProvider, selectedModel, temperature, maxTokens, activeCommand, multiFileMode, toolsEnabled, onPromptSubmit, currentDir]);

  const handleCancel = useCallback(() => {
    abortRef.current?.abort();
    setLoading(false);
  }, []);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

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

      {/* Provider + Model selector */}
      <AiProviderSelector
        providers={providers}
        selectedProvider={selectedProvider}
        selectedModel={selectedModel}
        onProviderChange={handleProviderSelect}
        onModelChange={setSelectedModel}
        providerModels={providerModels}
        keyedProviders={keyedProviders}
        loadingProviders={loadingProviders}
        loadingModels={loadingModels}
        loadingKeys={loadingKeys}
        loading={loading}
        showOptions={showOptions}
        onToggleOptions={() => setShowOptions((v) => !v)}
      />

      {/* Options panel */}
      {showOptions && (
        <div className="border-b border-border px-3 py-2">
          <AiOptionsPanel
            temperature={temperature}
            maxTokens={maxTokens}
            onTemperatureChange={setTemperature}
            onMaxTokensChange={setMaxTokens}
          />
        </div>
      )}

      {/* Inline API key setup */}
      {showKeySetup &&
        selectedProvider !== "default" &&
        isCloudProvider(selectedProvider) &&
        !loadingKeys &&
        !keyedProviders.has(selectedProvider) && (
          <ProviderKeySetup
            providerName={selectedProvider}
            onKeySaved={handleProviderKeySaved}
            onDismiss={() => setShowKeySetup(false)}
          />
        )}

      {/* Prompt input */}
      <div className="border-b border-border p-3">
        <AiPromptInput
          value={prompt}
          onChange={setPrompt}
          onSubmit={() => void handleSubmit()}
          activeCommand={activeCommand}
          onCommandSelect={handleCommandSelect}
          onCommandClear={() => setActiveCommand(null)}
          promptHistory={promptHistory}
          disabled={loading}
          placeholder={
            fileContent.trim()
              ? "Describe the change... (Ctrl+Enter to send, / for commands)"
              : "Describe what to generate... (Ctrl+Enter to send, / for commands)"
          }
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
          <Button
            size="sm"
            variant={multiFileMode ? "default" : "outline"}
            onClick={() => setMultiFileMode((v) => !v)}
            disabled={loading}
            className="h-7 gap-1.5 text-xs"
            title="Generate edits across multiple files using the ### FILE: format"
          >
            <FolderEdit className="size-3" />
            Multi-file
          </Button>
          <Button
            size="sm"
            variant={compareMode ? "default" : "outline"}
            onClick={() => setCompareMode((v) => !v)}
            disabled={loading}
            className="h-7 gap-1.5 text-xs"
            title="Compare two models side by side"
          >
            <GitCompare className="size-3" />
            Compare
          </Button>
          <Button
            size="sm"
            variant={toolsEnabled ? "default" : "outline"}
            onClick={() => {
              const next = !toolsEnabled;
              setToolsEnabled(next);
              if (typeof window !== "undefined") {
                localStorage.setItem("bmt_ai_tools_enabled", next ? "1" : "0");
              }
            }}
            disabled={loading}
            className="h-7 gap-1.5 text-xs"
            title="Enable AI tool use (read files, run commands, search code)"
          >
            <Wrench className="size-3" />
            Tools
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
          {/* Status bar: provider · model · filename */}
          <span className="ml-auto flex items-center gap-1 text-[10px] text-muted-foreground min-w-0">
            {selectedProvider !== "default" && (
              <>
                <HealthDot
                  healthy={providers.find((p) => p.name === selectedProvider)?.healthy ?? false}
                />
                <span className="shrink-0">{providerLabel(selectedProvider)}</span>
                {selectedModel !== "default" && (
                  <span className="opacity-60 truncate">
                    &middot;{" "}
                    {selectedModel.includes("/")
                      ? selectedModel.split("/").slice(1).join("/")
                      : selectedModel}
                  </span>
                )}
              </>
            )}
            {filePath && fileContent.trim() && (
              <span
                className={[
                  "truncate",
                  selectedProvider !== "default" ? "ml-1 opacity-60" : "",
                ].join(" ")}
              >
                {filePath.split("/").pop()}
              </span>
            )}
          </span>
        </div>
      </div>

      {/* Response area */}
      <AiResponseArea
        response={response}
        loading={loading}
        toolCalls={toolCallLog}
        showDiff={showDiff}
        onShowDiff={setShowDiff}
        compareMode={compareMode}
        onCloseCompare={() => setCompareMode(false)}
        multiFileMode={multiFileMode}
        onCloseMultiFile={() => setMultiFileMode(false)}
        fileContent={fileContent}
        language={language}
        filePath={filePath}
        currentDir={currentDir}
        temperature={temperature}
        maxTokens={maxTokens}
        onApply={onApply}
        onFileCreated={onFileCreated}
        extractCode={extractCode}
      />
    </div>
  );
}
