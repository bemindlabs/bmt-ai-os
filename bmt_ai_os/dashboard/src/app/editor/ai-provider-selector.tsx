"use client";

import { Loader2, AlertTriangle, ChevronDown, Settings2 } from "lucide-react";
import type { Provider } from "@/lib/api";

// ---------------------------------------------------------------------------
// Provider display helpers
// ---------------------------------------------------------------------------

export const PROVIDER_LABELS: Record<string, string> = {
  anthropic: "Claude",
  openai: "OpenAI",
  gemini: "Gemini",
  groq: "Groq",
  mistral: "Mistral",
  ollama: "Ollama",
  vllm: "vLLM",
  llamacpp: "llama.cpp",
};

export function providerLabel(name: string): string {
  return PROVIDER_LABELS[name.toLowerCase()] ?? name;
}

/** Cloud providers that require a configured API key */
export const CLOUD_PROVIDER_NAMES = new Set([
  "anthropic",
  "claude",
  "openai",
  "gemini",
  "google",
  "groq",
  "mistral",
]);

export function isCloudProvider(name: string): boolean {
  return CLOUD_PROVIDER_NAMES.has(name.toLowerCase());
}

// ---------------------------------------------------------------------------
// HealthDot
// ---------------------------------------------------------------------------

export function HealthDot({ healthy }: { healthy: boolean }) {
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

export function ProviderPill({
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
// AiProviderSelector
// ---------------------------------------------------------------------------

interface AiProviderSelectorProps {
  providers: Provider[];
  selectedProvider: string;
  selectedModel: string;
  onProviderChange: (name: string) => void;
  onModelChange: (model: string) => void;
  providerModels: Record<string, string[]>;
  keyedProviders: Set<string>;
  loadingProviders: boolean;
  loadingModels: boolean;
  loadingKeys: boolean;
  loading: boolean;
  showOptions: boolean;
  onToggleOptions: () => void;
}

export function AiProviderSelector({
  providers,
  selectedProvider,
  selectedModel,
  onProviderChange,
  onModelChange,
  providerModels,
  keyedProviders,
  loadingProviders,
  loadingModels,
  loadingKeys,
  loading,
  showOptions,
  onToggleOptions,
}: AiProviderSelectorProps) {
  return (
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
            onClick={() => onProviderChange("default")}
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
              onSelect={() => onProviderChange(p.name)}
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
              onChange={(e) => onModelChange(e.target.value)}
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
            onClick={onToggleOptions}
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
            onClick={onToggleOptions}
            className="rounded p-1 text-muted-foreground hover:text-foreground hover:bg-muted"
            title="Model options"
            aria-expanded={showOptions}
          >
            <Settings2 className="size-3.5" />
          </button>
        </div>
      )}
    </div>
  );
}
