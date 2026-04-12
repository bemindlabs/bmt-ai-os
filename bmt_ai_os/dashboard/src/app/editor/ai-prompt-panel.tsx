"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  streamChat,
  fetchProviders,
  fetchProviderModels,
  fetchProviderKeys,
  writeFile,
} from "@/lib/api";
import type { ChatMessage, Provider } from "@/lib/api";
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
  AlertTriangle,
  ChevronDown,
  GitCompare,
} from "lucide-react";
import { ProviderKeySetup } from "./provider-key-setup";
import { ModelCompare } from "./model-compare";

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
// Provider display helpers
// ---------------------------------------------------------------------------

const PROVIDER_LABELS: Record<string, string> = {
  anthropic: "Claude",
  openai: "OpenAI",
  gemini: "Gemini",
  groq: "Groq",
  mistral: "Mistral",
  ollama: "Ollama",
  vllm: "vLLM",
  llamacpp: "llama.cpp",
};

function providerLabel(name: string): string {
  return PROVIDER_LABELS[name.toLowerCase()] ?? name;
}

/** Cloud providers that require a configured API key */
const CLOUD_PROVIDER_NAMES = new Set([
  "anthropic",
  "claude",
  "openai",
  "gemini",
  "google",
  "groq",
  "mistral",
]);

function isCloudProvider(name: string): boolean {
  return CLOUD_PROVIDER_NAMES.has(name.toLowerCase());
}

// ---------------------------------------------------------------------------
// HealthDot
// ---------------------------------------------------------------------------

function HealthDot({ healthy }: { healthy: boolean }) {
  return (
    <span
      className={`inline-block size-1.5 rounded-full shrink-0 ${
        healthy ? "bg-green-500" : "bg-red-500"
      }`}
      aria-label={healthy ? "healthy" : "unhealthy"}
    />
  );
}

// ---------------------------------------------------------------------------
// ProviderPill
// ---------------------------------------------------------------------------

interface ProviderPillProps {
  provider: Provider;
  selected: boolean;
  missingKey: boolean;
  onSelect: () => void;
  disabled: boolean;
}

function ProviderPill({
  provider,
  selected,
  missingKey,
  onSelect,
  disabled,
}: ProviderPillProps) {
  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={disabled}
      title={
        missingKey
          ? `${providerLabel(provider.name)} — no API key configured`
          : providerLabel(provider.name)
      }
      className={[
        "inline-flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-medium",
        "border transition-colors focus:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        selected
          ? "border-primary bg-primary/10 text-primary"
          : "border-border bg-background text-muted-foreground hover:text-foreground hover:border-muted-foreground",
        disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer",
      ].join(" ")}
    >
      <HealthDot healthy={provider.healthy} />
      <span>{providerLabel(provider.name)}</span>
      {missingKey && (
        <AlertTriangle className="size-2.5 text-yellow-500 ml-0.5" />
      )}
    </button>
  );
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

  // ---------------------------------------------------------------------------
  // Provider + model state
  // ---------------------------------------------------------------------------

  const [providers, setProviders] = useState<Provider[]>([]);
  const [loadingProviders, setLoadingProviders] = useState(false);

  /** provider name → list of available model ids */
  const [providerModels, setProviderModels] = useState<Record<string, string[]>>({});
  const [loadingModels, setLoadingModels] = useState(false);

  /** provider names that have at least one active API key */
  const [keyedProviders, setKeyedProviders] = useState<Set<string>>(new Set());
  const [loadingKeys, setLoadingKeys] = useState(false);

  /** "default" = auto-route to active provider; otherwise explicit provider name */
  const [selectedProvider, setSelectedProvider] = useState<string>(
    () =>
      (typeof window !== "undefined" && localStorage.getItem(STORAGE_PROVIDER)) ||
      "default",
  );

  const [selectedModel, setSelectedModel] = useState<string>(
    () =>
      (typeof window !== "undefined" && localStorage.getItem(STORAGE_MODEL)) ||
      "default",
  );

  /** Show the inline key-setup widget for the selected cloud provider */
  const [showKeySetup, setShowKeySetup] = useState(false);

  // Compare mode
  const [compareMode, setCompareMode] = useState(false);

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

  // ---------------------------------------------------------------------------
  // Persist settings
  // ---------------------------------------------------------------------------

  useEffect(() => {
    localStorage.setItem(STORAGE_PROVIDER, selectedProvider);
  }, [selectedProvider]);
  useEffect(() => {
    localStorage.setItem(STORAGE_MODEL, selectedModel);
  }, [selectedModel]);
  useEffect(() => {
    localStorage.setItem(STORAGE_TEMP, String(temperature));
  }, [temperature]);
  useEffect(() => {
    localStorage.setItem(STORAGE_TOKENS, String(maxTokens));
  }, [maxTokens]);

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
          if (r.status === "fulfilled" && r.value.hasKey) {
            keyed.add(r.value.name);
          }
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

    // /v1/models returns all available models across all providers. We assign
    // them per provider by matching on the "provider/" prefix in the model id.
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
      // Show key setup when a cloud provider without a key is selected
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
        if (hasKey) {
          setKeyedProviders((prev) => new Set([...prev, selectedProvider]));
        }
      })
      .catch(() => null)
      .finally(() => setShowKeySetup(false));
  }, [selectedProvider]);

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

    // Build the model string: "provider/model" format when a specific
    // provider is selected, plain model otherwise (backward-compatible).
    let modelArg = selectedModel;
    if (selectedProvider !== "default") {
      if (!selectedModel || selectedModel === "default") {
        modelArg = selectedProvider;
      } else if (!selectedModel.toLowerCase().startsWith(selectedProvider.toLowerCase() + "/")) {
        modelArg = `${selectedProvider}/${selectedModel}`;
      }
    }

    try {
      const reader = await streamChat(
        {
          model: modelArg,
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
  }, [prompt, fileContent, filePath, language, loading, selectedProvider, selectedModel, temperature, maxTokens]);

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

      {/* Provider + Model selector + options */}
      <div className="border-b border-border px-3 py-2 space-y-2">

        {/* Provider pills */}
        <div className="space-y-1">
          <label className="text-[10px] text-muted-foreground uppercase tracking-wide">
            Provider
          </label>
          <div className="flex flex-wrap gap-1">
            {/* "auto" pill — backward-compatible, routes to active provider */}
            <button
              type="button"
              onClick={() => handleProviderSelect("default")}
              disabled={loading}
              className={[
                "inline-flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-medium",
                "border transition-colors focus:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                selectedProvider === "default"
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border bg-background text-muted-foreground hover:text-foreground hover:border-muted-foreground",
                loading ? "opacity-50 cursor-not-allowed" : "cursor-pointer",
              ].join(" ")}
            >
              <span className="inline-block size-1.5 rounded-full bg-blue-400 shrink-0" />
              auto
            </button>

            {loadingProviders && (
              <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground px-1">
                <Loader2 className="size-2.5 animate-spin" />
                Loading...
              </span>
            )}

            {providers.map((p) => (
              <ProviderPill
                key={p.name}
                provider={p}
                selected={selectedProvider === p.name}
                missingKey={
                  isCloudProvider(p.name) &&
                  !loadingKeys &&
                  !keyedProviders.has(p.name)
                }
                onSelect={() => handleProviderSelect(p.name)}
                disabled={loading}
              />
            ))}
          </div>
        </div>

        {/* Model dropdown — shown only when a specific provider is selected */}
        {selectedProvider !== "default" && (
          <div className="flex items-center gap-2">
            <label className="text-[10px] text-muted-foreground shrink-0 uppercase tracking-wide">
              Model
            </label>
            <div className="relative flex-1">
              <select
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
                className="w-full h-7 rounded border border-input bg-background pl-2 pr-6 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring appearance-none"
                disabled={loading || loadingModels}
              >
                <option value="default">
                  default ({providerLabel(selectedProvider)})
                </option>
                {(providerModels[selectedProvider] ?? []).map((id) => (
                  <option key={id} value={id}>
                    {id}
                  </option>
                ))}
                {loadingModels && <option disabled>Loading models...</option>}
              </select>
              <ChevronDown className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 size-3 text-muted-foreground" />
            </div>
            <button
              onClick={() => setShowOptions(!showOptions)}
              className="rounded p-1 text-muted-foreground hover:text-foreground hover:bg-muted"
              title="Model options"
              aria-expanded={showOptions}
            >
              <Settings2 className="size-3.5" />
            </button>
          </div>
        )}

        {/* Settings gear shown in auto mode (no model row) */}
        {selectedProvider === "default" && (
          <div className="flex justify-end">
            <button
              onClick={() => setShowOptions(!showOptions)}
              className="rounded p-1 text-muted-foreground hover:text-foreground hover:bg-muted"
              title="Model options"
              aria-expanded={showOptions}
            >
              <Settings2 className="size-3.5" />
            </button>
          </div>
        )}

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

      {/* Inline API key setup — shown when a cloud provider without a key is selected */}
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
                  healthy={
                    providers.find((p) => p.name === selectedProvider)
                      ?.healthy ?? false
                  }
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

      {/* Response area — compare mode or normal */}
      {compareMode ? (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <ModelCompare
            prompt={prompt}
            fileContent={fileContent}
            filePath={filePath}
            language={language}
            temperature={temperature}
            maxTokens={maxTokens}
            onApply={onApply}
            onClose={() => setCompareMode(false)}
          />
        </div>
      ) : (
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
      )}
    </div>
  );
}
