"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { streamChat } from "@/lib/api";
import type { Provider } from "@/lib/api";
import { useProviderCatalogue } from "./use-provider-catalogue";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { GitCompare, Loader2, Check, X, ChevronDown } from "lucide-react";
import { parseSSEChunk } from "@/lib/sse";
import { resolveModel, displayModelName } from "@/lib/utils";
import { buildEditorMessages, extractCode } from "./editor-prompts";
import { providerLabel } from "./ai-provider-selector";
import { estimateTokens } from "@/components/context-meter";

function formatLatency(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

// ---------------------------------------------------------------------------
// Column state type
// ---------------------------------------------------------------------------

interface ColumnState {
  model: string;
  provider: string;
  response: string;
  loading: boolean;
  error: string | null;
  latencyMs: number | null;
  startedAt: number | null;
}

function makeColumn(provider: string, model: string): ColumnState {
  return {
    provider,
    model,
    response: "",
    loading: false,
    error: null,
    latencyMs: null,
    startedAt: null,
  };
}

// ---------------------------------------------------------------------------
// ModelSelector sub-component
// ---------------------------------------------------------------------------

interface ModelSelectorProps {
  label: string;
  providers: Provider[];
  allModels: Record<string, string[]>;
  selectedProvider: string;
  selectedModel: string;
  disabled: boolean;
  onProviderChange: (p: string) => void;
  onModelChange: (m: string) => void;
}

function ModelSelector({
  label,
  providers,
  allModels,
  selectedProvider,
  selectedModel,
  disabled,
  onProviderChange,
  onModelChange,
}: ModelSelectorProps) {
  const models = allModels[selectedProvider] ?? [];

  return (
    <div className="flex flex-col gap-1 min-w-0">
      <span className="text-[10px] text-muted-foreground uppercase tracking-wide font-medium">
        {label}
      </span>
      <div className="flex flex-col gap-1">
        {/* Provider select */}
        <div className="relative">
          <select
            value={selectedProvider}
            onChange={(e) => onProviderChange(e.target.value)}
            disabled={disabled}
            className="w-full h-7 rounded border border-input bg-background pl-2 pr-6 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring appearance-none disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <option value="default">auto (default)</option>
            {providers.map((p) => (
              <option key={p.name} value={p.name}>
                {providerLabel(p.name)}
                {p.healthy ? "" : " (offline)"}
              </option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 size-3 text-muted-foreground" />
        </div>

        {/* Model select — only when a specific provider is chosen */}
        {selectedProvider !== "default" && (
          <div className="relative">
            <select
              value={selectedModel}
              onChange={(e) => onModelChange(e.target.value)}
              disabled={disabled}
              className="w-full h-7 rounded border border-input bg-background pl-2 pr-6 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring appearance-none disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <option value="default">default ({providerLabel(selectedProvider)})</option>
              {models.map((id) => (
                <option key={id} value={id}>
                  {displayModelName(id)}
                </option>
              ))}
            </select>
            <ChevronDown className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 size-3 text-muted-foreground" />
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ResultColumn sub-component
// ---------------------------------------------------------------------------

interface ResultColumnProps {
  col: ColumnState;
  side: "A" | "B";
  onApply: (code: string) => void;
}

function ResultColumn({ col, side, onApply }: ResultColumnProps) {
  const displayName =
    col.provider !== "default"
      ? col.model !== "default"
        ? displayModelName(col.model)
        : providerLabel(col.provider)
      : "auto";

  const handleApply = () => {
    onApply(extractCode(col.response));
  };

  return (
    <div className="flex flex-col min-h-0 flex-1 border border-border rounded overflow-hidden">
      {/* Column header */}
      <div className="flex items-center justify-between px-2 py-1.5 bg-muted/40 border-b border-border shrink-0">
        <div className="flex items-center gap-1.5 min-w-0">
          <Badge
            variant={side === "A" ? "default" : "secondary"}
            className="text-[10px] px-1.5 py-0 h-4 shrink-0"
          >
            {side}
          </Badge>
          <span className="text-xs font-medium truncate">{displayName}</span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {col.latencyMs !== null && (
            <span className="text-[10px] text-muted-foreground font-mono">
              {formatLatency(col.latencyMs)}
            </span>
          )}
          {col.response && !col.loading && (
            <span className="text-[10px] text-muted-foreground font-mono">
              {estimateTokens(col.response)}tk
            </span>
          )}
          {col.loading && (
            <Loader2 className="size-3 animate-spin text-muted-foreground" />
          )}
        </div>
      </div>

      {/* Response body */}
      <div className="flex-1 overflow-auto p-2 min-h-0">
        {col.error ? (
          <p className="text-xs text-destructive font-mono whitespace-pre-wrap">
            {col.error}
          </p>
        ) : col.response ? (
          <pre className="whitespace-pre-wrap font-mono text-xs text-foreground leading-relaxed">
            {col.response}
          </pre>
        ) : col.loading ? (
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin" />
            <span>Generating...</span>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground italic">
            No response yet. Run a comparison to see results.
          </p>
        )}
      </div>

      {/* Apply button */}
      {col.response && !col.loading && !col.error && (
        <div className="shrink-0 border-t border-border px-2 py-1.5">
          <Button
            size="sm"
            onClick={handleApply}
            className="h-6 gap-1 text-xs w-full"
          >
            <Check className="size-3" />
            Apply {side}
          </Button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ModelCompare — main export
// ---------------------------------------------------------------------------

export interface ModelCompareProps {
  prompt: string;
  fileContent: string;
  filePath: string | null;
  language: string;
  temperature: number;
  maxTokens: number;
  onApply: (code: string) => void;
  onClose: () => void;
}

export function ModelCompare({
  prompt,
  fileContent,
  filePath,
  language,
  temperature,
  maxTokens,
  onApply,
  onClose,
}: ModelCompareProps) {
  // Provider / model catalogue (shared hook)
  const { providers, providerModels: allModels, loadingProviders: loadingCatalogue } =
    useProviderCatalogue();

  // Column A
  const [providerA, setProviderA] = useState<string>("default");
  const [modelA, setModelA] = useState<string>("default");

  // Column B
  const [providerB, setProviderB] = useState<string>("default");
  const [modelB, setModelB] = useState<string>("default");

  // Results
  const [colA, setColA] = useState<ColumnState>(makeColumn("default", "default"));
  const [colB, setColB] = useState<ColumnState>(makeColumn("default", "default"));

  const abortA = useRef<AbortController | null>(null);
  const abortB = useRef<AbortController | null>(null);

  const isRunning = colA.loading || colB.loading;

  // Auto-select healthy providers once catalogue loads
  useEffect(() => {
    if (providers.length === 0 || Object.keys(allModels).length === 0) return;
    const healthy = providers.filter((p) => p.healthy);
    if (healthy[0]) {
      setProviderA(healthy[0].name);
      setModelA((allModels[healthy[0].name] ?? [])[0] ?? "default");
    }
    if (healthy[1]) {
      setProviderB(healthy[1].name);
      setModelB((allModels[healthy[1].name] ?? [])[0] ?? "default");
    }
  }, [providers, allModels]);

  // ---------------------------------------------------------------------------
  // Sync column state models when provider selectors change
  // ---------------------------------------------------------------------------

  const handleProviderAChange = useCallback(
    (p: string) => {
      setProviderA(p);
      setModelA((allModels[p] ?? [])[0] ?? "default");
    },
    [allModels],
  );

  const handleProviderBChange = useCallback(
    (p: string) => {
      setProviderB(p);
      setModelB((allModels[p] ?? [])[0] ?? "default");
    },
    [allModels],
  );

  // ---------------------------------------------------------------------------
  // Stream one column
  // ---------------------------------------------------------------------------

  async function streamColumn(
    modelArg: string,
    controller: AbortController,
    setCol: React.Dispatch<React.SetStateAction<ColumnState>>,
  ) {
    const startedAt = Date.now();
    setCol((prev) => ({
      ...prev,
      loading: true,
      response: "",
      error: null,
      latencyMs: null,
      startedAt,
    }));

    try {
      const reader = await streamChat(
        {
          model: modelArg,
          messages: buildEditorMessages({ prompt, fileContent, filePath, language }),
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
          setCol((prev) => ({ ...prev, response: accumulated }));
        }
      }

      setCol((prev) => ({
        ...prev,
        loading: false,
        latencyMs: Date.now() - startedAt,
      }));
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") {
        setCol((prev) => ({ ...prev, loading: false }));
      } else {
        setCol((prev) => ({
          ...prev,
          loading: false,
          error: err instanceof Error ? err.message : "Request failed",
          latencyMs: Date.now() - startedAt,
        }));
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Run comparison
  // ---------------------------------------------------------------------------

  const handleRun = useCallback(() => {
    if (!prompt.trim() || isRunning) return;

    // Abort any previous streams
    abortA.current?.abort();
    abortB.current?.abort();

    const ctrlA = new AbortController();
    const ctrlB = new AbortController();
    abortA.current = ctrlA;
    abortB.current = ctrlB;

    const mA = resolveModel(providerA, modelA);
    const mB = resolveModel(providerB, modelB);

    // Update column identities for the new run
    setColA(makeColumn(providerA, modelA));
    setColB(makeColumn(providerB, modelB));

    // Fire both streams simultaneously
    void Promise.all([
      streamColumn(mA, ctrlA, setColA),
      streamColumn(mB, ctrlB, setColB),
    ]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prompt, providerA, modelA, providerB, modelB, temperature, maxTokens, isRunning]);

  // ---------------------------------------------------------------------------
  // Cancel both streams
  // ---------------------------------------------------------------------------

  const handleCancel = useCallback(() => {
    abortA.current?.abort();
    abortB.current?.abort();
    setColA((prev) => ({ ...prev, loading: false }));
    setColB((prev) => ({ ...prev, loading: false }));
  }, []);

  // ---------------------------------------------------------------------------
  // Cleanup on unmount
  // ---------------------------------------------------------------------------

  useEffect(() => {
    return () => {
      abortA.current?.abort();
      abortB.current?.abort();
    };
  }, []);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const canRun = prompt.trim().length > 0 && !loadingCatalogue;

  return (
    <div className="flex h-full flex-col bg-background">
      {/* Header */}
      <div className="flex h-9 shrink-0 items-center justify-between border-b border-border bg-muted/30 px-3">
        <div className="flex items-center gap-1.5">
          <GitCompare className="size-3.5 text-blue-400" />
          <span className="text-xs font-medium">Model Comparison</span>
        </div>
        <button
          onClick={onClose}
          className="rounded p-0.5 text-muted-foreground hover:text-foreground"
          aria-label="Close compare panel"
        >
          <X className="size-3.5" />
        </button>
      </div>

      {/* Selector row */}
      <div className="shrink-0 border-b border-border px-3 py-2.5 space-y-2.5">
        {loadingCatalogue && (
          <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
            <Loader2 className="size-3 animate-spin" />
            Loading providers...
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <ModelSelector
            label="Model A"
            providers={providers}
            allModels={allModels}
            selectedProvider={providerA}
            selectedModel={modelA}
            disabled={isRunning}
            onProviderChange={handleProviderAChange}
            onModelChange={setModelA}
          />
          <ModelSelector
            label="Model B"
            providers={providers}
            allModels={allModels}
            selectedProvider={providerB}
            selectedModel={modelB}
            disabled={isRunning}
            onProviderChange={handleProviderBChange}
            onModelChange={setModelB}
          />
        </div>

        {/* Prompt preview */}
        {prompt.trim() && (
          <div className="rounded border border-border bg-muted/20 px-2 py-1.5">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide mb-0.5">
              Prompt
            </p>
            <p className="text-xs text-foreground line-clamp-2 font-mono">
              {prompt}
            </p>
          </div>
        )}

        {!prompt.trim() && (
          <p className="text-[10px] text-yellow-500">
            Enter a prompt in the AI Assistant panel first, then run a comparison.
          </p>
        )}

        {/* Action buttons */}
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            onClick={handleRun}
            disabled={!canRun || isRunning}
            className="h-7 gap-1.5 text-xs"
          >
            {isRunning ? (
              <>
                <Loader2 className="size-3 animate-spin" />
                Running...
              </>
            ) : (
              <>
                <GitCompare className="size-3" />
                Run Comparison
              </>
            )}
          </Button>
          {isRunning && (
            <Button
              size="sm"
              variant="outline"
              onClick={handleCancel}
              className="h-7 text-xs"
            >
              Cancel
            </Button>
          )}
        </div>
      </div>

      {/* Side-by-side results */}
      <div className="flex min-h-0 flex-1 gap-2 overflow-hidden p-2">
        <ResultColumn col={colA} side="A" onApply={onApply} />
        <ResultColumn col={colB} side="B" onApply={onApply} />
      </div>
    </div>
  );
}
