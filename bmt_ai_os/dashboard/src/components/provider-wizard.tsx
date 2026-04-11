"use client";

import { useState, useCallback } from "react";
import {
  Server,
  Cloud,
  Bot,
  Cpu,
  Zap,
  Wind,
  Terminal,
  Box,
  ChevronRight,
  ChevronLeft,
  X,
  CheckCircle,
  XCircle,
  Loader2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Provider metadata
// ---------------------------------------------------------------------------

interface ProviderMeta {
  id: string;
  label: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  defaultBaseUrl: string;
  isLocal: boolean;
  modelPlaceholder: string;
}

const PROVIDERS: ProviderMeta[] = [
  {
    id: "ollama",
    label: "Ollama",
    description: "Local LLM inference with Ollama",
    icon: Server,
    defaultBaseUrl: "http://localhost:11434",
    isLocal: true,
    modelPlaceholder: "qwen2.5-coder:7b",
  },
  {
    id: "openai",
    label: "OpenAI",
    description: "GPT-4o and o-series models",
    icon: Cloud,
    defaultBaseUrl: "https://api.openai.com/v1",
    isLocal: false,
    modelPlaceholder: "gpt-4o",
  },
  {
    id: "anthropic",
    label: "Anthropic",
    description: "Claude Sonnet and Haiku models",
    icon: Bot,
    defaultBaseUrl: "https://api.anthropic.com",
    isLocal: false,
    modelPlaceholder: "claude-sonnet-4-6",
  },
  {
    id: "gemini",
    label: "Gemini",
    description: "Google Gemini Pro and Flash models",
    icon: Zap,
    defaultBaseUrl: "https://generativelanguage.googleapis.com",
    isLocal: false,
    modelPlaceholder: "gemini-2.0-flash",
  },
  {
    id: "groq",
    label: "Groq",
    description: "Ultra-fast inference via Groq LPU",
    icon: Cpu,
    defaultBaseUrl: "https://api.groq.com/openai/v1",
    isLocal: false,
    modelPlaceholder: "llama-3.3-70b-versatile",
  },
  {
    id: "mistral",
    label: "Mistral",
    description: "Mistral and Codestral models",
    icon: Wind,
    defaultBaseUrl: "https://api.mistral.ai/v1",
    isLocal: false,
    modelPlaceholder: "mistral-large-latest",
  },
  {
    id: "vllm",
    label: "vLLM",
    description: "High-throughput local vLLM server",
    icon: Terminal,
    defaultBaseUrl: "http://localhost:8000/v1",
    isLocal: true,
    modelPlaceholder: "Qwen/Qwen2.5-Coder-7B-Instruct",
  },
  {
    id: "llamacpp",
    label: "llama.cpp",
    description: "Lightweight llama.cpp HTTP server",
    icon: Box,
    defaultBaseUrl: "http://localhost:8080",
    isLocal: true,
    modelPlaceholder: "qwen2.5-coder-7b-q4_k_m.gguf",
  },
];

// ---------------------------------------------------------------------------
// Wizard state
// ---------------------------------------------------------------------------

interface WizardState {
  provider: ProviderMeta | null;
  authMethod: "none" | "api_key";
  baseUrl: string;
  apiKey: string;
  defaultModel: string;
  testStatus: "idle" | "loading" | "success" | "error";
  testMessage: string;
  availableModels: string[];
  modelsLoading: boolean;
  modelsError: string;
}

const initialState: WizardState = {
  provider: null,
  authMethod: "none",
  baseUrl: "",
  apiKey: "",
  defaultModel: "",
  testStatus: "idle",
  testMessage: "",
  availableModels: [],
  modelsLoading: false,
  modelsError: "",
};

// ---------------------------------------------------------------------------
// Step components
// ---------------------------------------------------------------------------

function StepSelectProvider({
  selected,
  onSelect,
}: {
  selected: ProviderMeta | null;
  onSelect: (p: ProviderMeta) => void;
}) {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-semibold">Select Provider Type</h2>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Choose the LLM inference backend you want to configure.
        </p>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {PROVIDERS.map((p) => {
          const Icon = p.icon;
          const isSelected = selected?.id === p.id;
          return (
            <button
              key={p.id}
              onClick={() => onSelect(p)}
              aria-pressed={isSelected}
              className={cn(
                "flex flex-col items-start gap-2 rounded-xl border p-3 text-left text-sm transition-colors outline-none",
                "hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring",
                isSelected
                  ? "border-primary bg-primary/5 ring-1 ring-primary"
                  : "border-border bg-card"
              )}
            >
              <div className="flex w-full items-center justify-between gap-2">
                <Icon className="size-4 shrink-0 text-muted-foreground" />
                {p.isLocal && (
                  <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                    local
                  </Badge>
                )}
              </div>
              <div>
                <p className="font-medium leading-snug">{p.label}</p>
                <p className="mt-0.5 text-xs text-muted-foreground line-clamp-2">
                  {p.description}
                </p>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function StepAuthMethod({
  provider,
  authMethod,
  onSelect,
}: {
  provider: ProviderMeta;
  authMethod: "none" | "api_key";
  onSelect: (m: "none" | "api_key") => void;
}) {
  const options: { value: "none" | "api_key"; label: string; description: string }[] =
    provider.isLocal
      ? [
          {
            value: "none",
            label: "No Authentication",
            description: "Local provider — no API key required.",
          },
          {
            value: "api_key",
            label: "API Key",
            description: "Optional bearer token if your server is secured.",
          },
        ]
      : [
          {
            value: "api_key",
            label: "API Key",
            description: "Authenticate using a provider-issued API key.",
          },
        ];

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-semibold">Choose Authentication Method</h2>
        <p className="mt-0.5 text-sm text-muted-foreground">
          How should the controller authenticate with {provider.label}?
        </p>
      </div>
      <div className="flex flex-col gap-3">
        {options.map((opt) => {
          const isSelected = authMethod === opt.value;
          return (
            <button
              key={opt.value}
              onClick={() => onSelect(opt.value)}
              aria-pressed={isSelected}
              className={cn(
                "flex items-start gap-3 rounded-xl border p-4 text-left text-sm transition-colors outline-none",
                "hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring",
                isSelected
                  ? "border-primary bg-primary/5 ring-1 ring-primary"
                  : "border-border bg-card"
              )}
            >
              <span
                className={cn(
                  "mt-0.5 size-4 shrink-0 rounded-full border-2 transition-colors",
                  isSelected ? "border-primary bg-primary" : "border-muted-foreground"
                )}
              />
              <div>
                <p className="font-medium">{opt.label}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">{opt.description}</p>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function StepCredentials({
  provider,
  authMethod,
  baseUrl,
  apiKey,
  onBaseUrlChange,
  onApiKeyChange,
}: {
  provider: ProviderMeta;
  authMethod: "none" | "api_key";
  baseUrl: string;
  apiKey: string;
  onBaseUrlChange: (v: string) => void;
  onApiKeyChange: (v: string) => void;
}) {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-semibold">Enter Credentials</h2>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Configure the connection details for {provider.label}.
        </p>
      </div>
      <div className="space-y-4">
        <div className="space-y-1.5">
          <label htmlFor="base-url" className="text-sm font-medium">
            Base URL
          </label>
          <Input
            id="base-url"
            type="url"
            placeholder={provider.defaultBaseUrl}
            value={baseUrl}
            onChange={(e) => onBaseUrlChange(e.target.value)}
            autoComplete="off"
          />
          <p className="text-xs text-muted-foreground">
            The root endpoint for the {provider.label} API.
          </p>
        </div>

        {authMethod === "api_key" && (
          <div className="space-y-1.5">
            <label htmlFor="api-key" className="text-sm font-medium">
              API Key
            </label>
            <Input
              id="api-key"
              type="password"
              placeholder="sk-..."
              value={apiKey}
              onChange={(e) => onApiKeyChange(e.target.value)}
              autoComplete="new-password"
            />
            <p className="text-xs text-muted-foreground">
              Your secret API key — stored securely on the controller.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function StepTestConnection({
  provider,
  testStatus,
  testMessage,
  onTest,
}: {
  provider: ProviderMeta;
  testStatus: "idle" | "loading" | "success" | "error";
  testMessage: string;
  onTest: () => void;
}) {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-semibold">Test Connection</h2>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Verify the controller can reach {provider.label} before registering.
        </p>
      </div>

      <Card>
        <CardContent className="pt-4 space-y-4">
          <div className="flex items-center gap-3">
            <div
              className={cn(
                "flex size-10 shrink-0 items-center justify-center rounded-full",
                testStatus === "idle" && "bg-muted",
                testStatus === "loading" && "bg-muted",
                testStatus === "success" && "bg-green-500/10",
                testStatus === "error" && "bg-destructive/10"
              )}
            >
              {testStatus === "loading" && (
                <Loader2 className="size-5 animate-spin text-muted-foreground" />
              )}
              {testStatus === "success" && (
                <CheckCircle className="size-5 text-green-500" />
              )}
              {testStatus === "error" && (
                <XCircle className="size-5 text-destructive" />
              )}
              {testStatus === "idle" && (
                <provider.icon className="size-5 text-muted-foreground" />
              )}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">
                {testStatus === "idle" && `Ready to test ${provider.label}`}
                {testStatus === "loading" && "Connecting…"}
                {testStatus === "success" && "Connection successful"}
                {testStatus === "error" && "Connection failed"}
              </p>
              {testMessage && (
                <p className="mt-0.5 text-xs text-muted-foreground truncate">
                  {testMessage}
                </p>
              )}
            </div>
          </div>

          <Button
            variant="outline"
            size="sm"
            onClick={onTest}
            disabled={testStatus === "loading"}
            className="w-full"
          >
            {testStatus === "loading" ? (
              <>
                <Loader2 className="size-3.5 animate-spin" />
                Testing…
              </>
            ) : testStatus === "success" ? (
              "Test Again"
            ) : (
              "Test Connection"
            )}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

function StepSelectModel({
  provider,
  defaultModel,
  availableModels,
  modelsLoading,
  modelsError,
  onModelChange,
}: {
  provider: ProviderMeta;
  defaultModel: string;
  availableModels: string[];
  modelsLoading: boolean;
  modelsError: string;
  onModelChange: (v: string) => void;
}) {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-semibold">Select Default Model</h2>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Choose which model the controller should use by default for {provider.label}.
        </p>
      </div>

      <div className="space-y-1.5">
        <label htmlFor="model-input" className="text-sm font-medium">
          Model ID
        </label>
        <Input
          id="model-input"
          type="text"
          placeholder={provider.modelPlaceholder}
          value={defaultModel}
          onChange={(e) => onModelChange(e.target.value)}
          autoComplete="off"
          list="model-suggestions"
        />
        {availableModels.length > 0 && (
          <datalist id="model-suggestions">
            {availableModels.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        )}
        <p className="text-xs text-muted-foreground">
          Type a model ID or pick from the list fetched from {provider.label}.
        </p>
      </div>

      {modelsLoading && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="size-3 animate-spin" />
          Fetching available models…
        </div>
      )}

      {modelsError && (
        <p className="text-xs text-destructive">{modelsError}</p>
      )}

      {!modelsLoading && availableModels.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Available Models
          </p>
          <div className="flex flex-wrap gap-1.5 max-h-32 overflow-y-auto">
            {availableModels.map((m) => (
              <button
                key={m}
                onClick={() => onModelChange(m)}
                className={cn(
                  "rounded-lg border px-2 py-1 text-xs transition-colors outline-none",
                  "hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring",
                  defaultModel === m
                    ? "border-primary bg-primary/5 font-medium"
                    : "border-border bg-card"
                )}
              >
                {m}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stepper UI
// ---------------------------------------------------------------------------

const STEP_LABELS = [
  "Provider",
  "Auth",
  "Credentials",
  "Test",
  "Model",
];

function Stepper({ current }: { current: number }) {
  return (
    <ol className="flex items-center gap-0" aria-label="Wizard steps">
      {STEP_LABELS.map((label, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <li key={label} className="flex items-center">
            <div className="flex flex-col items-center gap-1">
              <span
                aria-current={active ? "step" : undefined}
                className={cn(
                  "flex size-6 items-center justify-center rounded-full text-xs font-semibold transition-colors",
                  done && "bg-primary text-primary-foreground",
                  active && "bg-primary text-primary-foreground ring-2 ring-primary/30",
                  !done && !active && "bg-muted text-muted-foreground"
                )}
              >
                {done ? <CheckCircle className="size-3.5" /> : i + 1}
              </span>
              <span
                className={cn(
                  "hidden text-[10px] font-medium sm:block",
                  active ? "text-foreground" : "text-muted-foreground"
                )}
              >
                {label}
              </span>
            </div>
            {i < STEP_LABELS.length - 1 && (
              <div
                className={cn(
                  "mx-1 mb-4 h-px w-8 flex-1 transition-colors sm:w-12",
                  done ? "bg-primary" : "bg-border"
                )}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}

// ---------------------------------------------------------------------------
// Main wizard
// ---------------------------------------------------------------------------

interface ProviderWizardProps {
  onClose: () => void;
  onComplete: () => void;
}

export function ProviderWizard({ onClose, onComplete }: ProviderWizardProps) {
  const [step, setStep] = useState(0);
  const [state, setState] = useState<WizardState>(initialState);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");

  const update = useCallback(
    (patch: Partial<WizardState>) => setState((s) => ({ ...s, ...patch })),
    []
  );

  // ---- step validation ----------------------------------------------------

  function canAdvance(): boolean {
    switch (step) {
      case 0:
        return state.provider !== null;
      case 1:
        return true; // authMethod always has a default
      case 2: {
        const url = state.baseUrl.trim();
        if (!url) return false;
        if (state.authMethod === "api_key" && !state.provider?.isLocal) {
          return state.apiKey.trim().length > 0;
        }
        return true;
      }
      case 3:
        return state.testStatus === "success";
      case 4:
        return state.defaultModel.trim().length > 0;
      default:
        return true;
    }
  }

  // ---- navigation ---------------------------------------------------------

  function goNext() {
    if (step === 1 && state.provider) {
      // Auto-fill base URL when entering credentials step
      if (!state.baseUrl) {
        update({ baseUrl: state.provider.defaultBaseUrl });
      }
      // Force api_key for cloud providers
      if (!state.provider.isLocal) {
        update({ authMethod: "api_key" });
      }
    }

    if (step === 3 && state.provider) {
      // Fetch models when entering model selection step
      fetchModels();
    }

    setStep((s) => s + 1);
  }

  function goBack() {
    // Reset test status when going back from test step
    if (step === 3) {
      update({ testStatus: "idle", testMessage: "" });
    }
    setStep((s) => s - 1);
  }

  // ---- API calls ----------------------------------------------------------

  async function handleTest() {
    if (!state.provider) return;
    update({ testStatus: "loading", testMessage: "" });

    try {
      const res = await fetch(
        `/api/v1/providers/config/${state.provider.id}/test`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            base_url: state.baseUrl,
            api_key: state.apiKey || undefined,
          }),
        }
      );

      if (res.ok) {
        const data = (await res.json()) as { message?: string };
        update({
          testStatus: "success",
          testMessage: data.message ?? "Provider responded successfully.",
        });
      } else {
        const data = (await res.json().catch(() => ({}))) as { detail?: string };
        update({
          testStatus: "error",
          testMessage: data.detail ?? `HTTP ${res.status}: ${res.statusText}`,
        });
      }
    } catch (err) {
      update({
        testStatus: "error",
        testMessage: err instanceof Error ? err.message : "Network error",
      });
    }
  }

  async function fetchModels() {
    if (!state.provider) return;
    update({ modelsLoading: true, modelsError: "", availableModels: [] });

    try {
      const res = await fetch(
        `/api/v1/providers/config/${state.provider.id}/models`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            base_url: state.baseUrl,
            api_key: state.apiKey || undefined,
          }),
        }
      );

      if (res.ok) {
        const data = (await res.json()) as { models?: string[] };
        update({
          modelsLoading: false,
          availableModels: data.models ?? [],
        });
      } else {
        update({
          modelsLoading: false,
          modelsError: "Could not fetch models — enter an ID manually.",
        });
      }
    } catch {
      update({
        modelsLoading: false,
        modelsError: "Could not fetch models — enter an ID manually.",
      });
    }
  }

  async function handleSubmit() {
    if (!state.provider) return;
    setSubmitting(true);
    setSubmitError("");

    try {
      const res = await fetch("/api/v1/providers/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: state.provider.id,
          base_url: state.baseUrl,
          api_key: state.apiKey || undefined,
          default_model: state.defaultModel,
        }),
      });

      if (res.ok) {
        onComplete();
      } else {
        const data = (await res.json().catch(() => ({}))) as { detail?: string };
        setSubmitError(data.detail ?? `HTTP ${res.status}: ${res.statusText}`);
      }
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Network error");
    } finally {
      setSubmitting(false);
    }
  }

  // ---- render -------------------------------------------------------------

  const provider = state.provider;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Provider setup wizard"
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm p-4"
    >
      <Card className="w-full max-w-2xl shadow-xl">
        <CardHeader className="border-b pb-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <CardTitle>Provider Setup Wizard</CardTitle>
              <CardDescription className="mt-1">
                Configure a new LLM provider in {STEP_LABELS.length} steps.
              </CardDescription>
            </div>
            <Button
              variant="ghost"
              size="icon"
              onClick={onClose}
              aria-label="Close wizard"
              className="shrink-0"
            >
              <X className="size-4" />
            </Button>
          </div>

          <div className="mt-4">
            <Stepper current={step} />
          </div>
        </CardHeader>

        <CardContent className="py-6 min-h-64">
          {step === 0 && (
            <StepSelectProvider
              selected={state.provider}
              onSelect={(p) =>
                update({
                  provider: p,
                  authMethod: p.isLocal ? "none" : "api_key",
                  baseUrl: "",
                  apiKey: "",
                  testStatus: "idle",
                  testMessage: "",
                  availableModels: [],
                  defaultModel: "",
                })
              }
            />
          )}

          {step === 1 && provider && (
            <StepAuthMethod
              provider={provider}
              authMethod={state.authMethod}
              onSelect={(m) => update({ authMethod: m })}
            />
          )}

          {step === 2 && provider && (
            <StepCredentials
              provider={provider}
              authMethod={state.authMethod}
              baseUrl={state.baseUrl}
              apiKey={state.apiKey}
              onBaseUrlChange={(v) => update({ baseUrl: v })}
              onApiKeyChange={(v) => update({ apiKey: v })}
            />
          )}

          {step === 3 && provider && (
            <StepTestConnection
              provider={provider}
              testStatus={state.testStatus}
              testMessage={state.testMessage}
              onTest={handleTest}
            />
          )}

          {step === 4 && provider && (
            <StepSelectModel
              provider={provider}
              defaultModel={state.defaultModel}
              availableModels={state.availableModels}
              modelsLoading={state.modelsLoading}
              modelsError={state.modelsError}
              onModelChange={(v) => update({ defaultModel: v })}
            />
          )}
        </CardContent>

        {/* Footer */}
        <div className="flex items-center justify-between border-t px-4 py-3">
          <Button
            variant="ghost"
            size="sm"
            onClick={goBack}
            disabled={step === 0}
          >
            <ChevronLeft className="size-3.5" />
            Back
          </Button>

          <div className="flex items-center gap-2">
            {submitError && (
              <p className="max-w-xs truncate text-xs text-destructive">
                {submitError}
              </p>
            )}

            {step < STEP_LABELS.length - 1 ? (
              <Button
                size="sm"
                onClick={goNext}
                disabled={!canAdvance()}
              >
                Next
                <ChevronRight className="size-3.5" />
              </Button>
            ) : (
              <Button
                size="sm"
                onClick={handleSubmit}
                disabled={!canAdvance() || submitting}
              >
                {submitting ? (
                  <>
                    <Loader2 className="size-3.5 animate-spin" />
                    Registering…
                  </>
                ) : (
                  "Register Provider"
                )}
              </Button>
            )}
          </div>
        </div>
      </Card>
    </div>
  );
}
