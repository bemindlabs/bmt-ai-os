"use client";

import { useCallback, useState } from "react";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, ExternalLink, KeyRound, Loader2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { saveProviderKey } from "@/lib/api";

// ---------------------------------------------------------------------------
// Provider metadata
// ---------------------------------------------------------------------------

interface ProviderMeta {
  /** Human-readable label, e.g. "Claude (Anthropic)" */
  label: string;
  /** URL where users can obtain an API key */
  keyUrl: string;
  /** Short domain shown as the link text */
  keyUrlLabel: string;
  /** Placeholder shown inside the masked input */
  placeholder: string;
}

const PROVIDER_META: Record<string, ProviderMeta> = {
  anthropic: {
    label: "Claude (Anthropic)",
    keyUrl: "https://console.anthropic.com",
    keyUrlLabel: "console.anthropic.com",
    placeholder: "sk-ant-api03-...",
  },
  claude: {
    label: "Claude (Anthropic)",
    keyUrl: "https://console.anthropic.com",
    keyUrlLabel: "console.anthropic.com",
    placeholder: "sk-ant-api03-...",
  },
  openai: {
    label: "OpenAI",
    keyUrl: "https://platform.openai.com/api-keys",
    keyUrlLabel: "platform.openai.com/api-keys",
    placeholder: "sk-...",
  },
  gemini: {
    label: "Gemini (Google)",
    keyUrl: "https://aistudio.google.com/apikey",
    keyUrlLabel: "aistudio.google.com/apikey",
    placeholder: "AIza...",
  },
  google: {
    label: "Gemini (Google)",
    keyUrl: "https://aistudio.google.com/apikey",
    keyUrlLabel: "aistudio.google.com/apikey",
    placeholder: "AIza...",
  },
  groq: {
    label: "Groq",
    keyUrl: "https://console.groq.com/keys",
    keyUrlLabel: "console.groq.com/keys",
    placeholder: "gsk_...",
  },
  mistral: {
    label: "Mistral",
    keyUrl: "https://console.mistral.ai/api-keys",
    keyUrlLabel: "console.mistral.ai/api-keys",
    placeholder: "...",
  },
};

function getProviderMeta(providerName: string): ProviderMeta {
  const key = providerName.toLowerCase();
  return (
    PROVIDER_META[key] ?? {
      label: providerName,
      keyUrl: "https://platform.openai.com/api-keys",
      keyUrlLabel: "provider API console",
      placeholder: "API key...",
    }
  );
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface ProviderKeySetupProps {
  providerName: string;
  onKeySaved: () => void;
  onDismiss: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

type SaveStatus = "idle" | "saving" | "success" | "error";

export function ProviderKeySetup({
  providerName,
  onKeySaved,
  onDismiss,
}: ProviderKeySetupProps) {
  const meta = getProviderMeta(providerName);

  const [apiKey, setApiKey] = useState("");
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle");
  const [errorMessage, setErrorMessage] = useState("");

  const handleSave = useCallback(async () => {
    const trimmed = apiKey.trim();
    if (!trimmed || saveStatus === "saving") return;

    setSaveStatus("saving");
    setErrorMessage("");

    try {
      await saveProviderKey(providerName, trimmed);
      setSaveStatus("success");
      // Give the user a brief moment to see the success state before the
      // parent re-checks whether a key now exists.
      setTimeout(() => {
        onKeySaved();
      }, 800);
    } catch (err) {
      setSaveStatus("error");
      setErrorMessage(
        err instanceof Error ? err.message : "Failed to save key",
      );
    }
  }, [apiKey, providerName, saveStatus, onKeySaved]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") void handleSave();
      if (e.key === "Escape") onDismiss();
    },
    [handleSave, onDismiss],
  );

  return (
    <div
      className="mx-3 my-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs"
      role="region"
      aria-label={`API key required for ${meta.label}`}
    >
      {/* Header row */}
      <div className="mb-2.5 flex items-start gap-2">
        <AlertTriangle
          className="mt-0.5 size-3.5 shrink-0 text-amber-500"
          aria-hidden="true"
        />
        <div className="flex-1 min-w-0">
          <p className="font-medium text-foreground leading-snug">
            {meta.label} API key required
          </p>
          <p className="mt-0.5 text-muted-foreground">
            Add a key to use this provider in the editor.
          </p>
        </div>
        <Badge variant="outline" className="shrink-0 text-[10px] border-amber-500/40 text-amber-600 dark:text-amber-400">
          No key
        </Badge>
      </div>

      {/* Key input */}
      <div className="mb-2">
        <label
          htmlFor={`provider-key-input-${providerName}`}
          className="mb-1 block text-[10px] uppercase tracking-wide text-muted-foreground"
        >
          API Key
        </label>
        <div className="flex items-center gap-1.5">
          <KeyRound className="size-3 shrink-0 text-muted-foreground" aria-hidden="true" />
          <Input
            id={`provider-key-input-${providerName}`}
            type="password"
            value={apiKey}
            onChange={(e) => {
              setApiKey(e.target.value);
              if (saveStatus === "error") setSaveStatus("idle");
            }}
            onKeyDown={handleKeyDown}
            placeholder={meta.placeholder}
            autoComplete="off"
            spellCheck={false}
            className="h-7 flex-1 font-mono text-xs"
            aria-describedby={
              saveStatus === "error"
                ? `provider-key-error-${providerName}`
                : undefined
            }
            disabled={saveStatus === "saving" || saveStatus === "success"}
          />
        </div>
      </div>

      {/* Inline feedback */}
      {saveStatus === "error" && errorMessage && (
        <div
          id={`provider-key-error-${providerName}`}
          className="mb-2 flex items-center gap-1.5 text-destructive"
          role="alert"
        >
          <XCircle className="size-3 shrink-0" aria-hidden="true" />
          <span>{errorMessage}</span>
        </div>
      )}
      {saveStatus === "success" && (
        <div
          className="mb-2 flex items-center gap-1.5 text-green-600 dark:text-green-400"
          role="status"
        >
          <CheckCircle2 className="size-3 shrink-0" aria-hidden="true" />
          <span>Key saved successfully</span>
        </div>
      )}

      {/* Action row */}
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          onClick={() => void handleSave()}
          disabled={!apiKey.trim() || saveStatus === "saving" || saveStatus === "success"}
          className="h-7 gap-1.5 text-xs"
        >
          {saveStatus === "saving" ? (
            <>
              <Loader2 className="size-3 animate-spin" aria-hidden="true" />
              Saving...
            </>
          ) : saveStatus === "success" ? (
            <>
              <CheckCircle2 className="size-3" aria-hidden="true" />
              Saved
            </>
          ) : (
            "Save Key"
          )}
        </Button>

        <Link
          href="/settings"
          className="text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
          onClick={onDismiss}
        >
          Go to Settings
        </Link>

        <button
          onClick={onDismiss}
          className="ml-auto text-xs text-muted-foreground hover:text-foreground"
          aria-label="Dismiss key setup"
          type="button"
        >
          Dismiss
        </button>
      </div>

      {/* Help link */}
      <div className="mt-2 border-t border-border/40 pt-2">
        <p className="text-[10px] text-muted-foreground">
          Get a key:{" "}
          <a
            href={meta.keyUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-0.5 text-primary underline underline-offset-2 hover:text-primary/80"
          >
            {meta.keyUrlLabel}
            <ExternalLink className="size-2.5" aria-hidden="true" />
          </a>
        </p>
      </div>
    </div>
  );
}
