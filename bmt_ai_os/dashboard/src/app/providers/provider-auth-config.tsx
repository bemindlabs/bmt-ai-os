"use client";

import { useState } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Key,
  Globe,
  ExternalLink,
  CheckCircle2,
  AlertCircle,
  Shield,
} from "lucide-react";
import { addProviderKey } from "@/lib/api";

// ---------------------------------------------------------------------------
// Provider metadata — auth types, docs links, key formats
// ---------------------------------------------------------------------------

interface ProviderAuthMeta {
  label: string;
  authType: "api-key" | "oauth" | "none";
  docsUrl: string;
  keyPlaceholder: string;
  keyPrefix?: string;
  description: string;
}

const PROVIDER_AUTH_META: Record<string, ProviderAuthMeta> = {
  anthropic: {
    label: "Anthropic (Claude)",
    authType: "api-key",
    docsUrl: "https://console.anthropic.com/settings/keys",
    keyPlaceholder: "sk-ant-api03-...",
    keyPrefix: "sk-ant-",
    description: "Claude models (Sonnet, Opus, Haiku). API key from Anthropic Console.",
  },
  openai: {
    label: "OpenAI (GPT / Codex)",
    authType: "api-key",
    docsUrl: "https://platform.openai.com/api-keys",
    keyPlaceholder: "sk-proj-...",
    keyPrefix: "sk-",
    description: "GPT-4o, GPT-4, o1, Codex models. API key from OpenAI Platform.",
  },
  gemini: {
    label: "Google (Gemini)",
    authType: "api-key",
    docsUrl: "https://aistudio.google.com/apikey",
    keyPlaceholder: "AIza...",
    keyPrefix: "AIza",
    description: "Gemini Pro, Gemini Flash models. API key from Google AI Studio.",
  },
  groq: {
    label: "Groq",
    authType: "api-key",
    docsUrl: "https://console.groq.com/keys",
    keyPlaceholder: "gsk_...",
    keyPrefix: "gsk_",
    description: "Fast inference for Llama, Mixtral. API key from Groq Console.",
  },
  mistral: {
    label: "Mistral AI",
    authType: "api-key",
    docsUrl: "https://console.mistral.ai/api-keys",
    keyPlaceholder: "...",
    description: "Mistral, Mixtral, Codestral models. API key from Mistral Console.",
  },
  ollama: {
    label: "Ollama (Local)",
    authType: "none",
    docsUrl: "https://ollama.com",
    keyPlaceholder: "",
    description: "Local LLM inference. No API key required — runs on device.",
  },
  vllm: {
    label: "vLLM (Local)",
    authType: "none",
    docsUrl: "https://docs.vllm.ai",
    keyPlaceholder: "",
    description: "High-throughput local inference. No API key required.",
  },
  llamacpp: {
    label: "llama.cpp (Local)",
    authType: "none",
    docsUrl: "https://github.com/ggerganov/llama.cpp",
    keyPlaceholder: "",
    description: "CPU/GPU inference via llama.cpp server. No API key required.",
  },
};

function getAuthMeta(providerName: string): ProviderAuthMeta {
  return (
    PROVIDER_AUTH_META[providerName.toLowerCase()] ?? {
      label: providerName,
      authType: "api-key",
      docsUrl: "",
      keyPlaceholder: "API key...",
      description: `${providerName} provider.`,
    }
  );
}

// ---------------------------------------------------------------------------
// ProviderAuthConfig component
// ---------------------------------------------------------------------------

interface ProviderAuthConfigProps {
  providerName: string;
  healthy: boolean;
  hasKeys: boolean;
  onKeyAdded?: () => void;
}

export function ProviderAuthConfig({
  providerName,
  healthy,
  hasKeys,
  onKeyAdded,
}: ProviderAuthConfigProps) {
  const meta = getAuthMeta(providerName);
  const [keyInput, setKeyInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<"idle" | "success" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState("");

  async function handleSave() {
    if (!keyInput.trim()) return;
    setSaving(true);
    setStatus("idle");
    try {
      await addProviderKey(providerName, keyInput.trim());
      setStatus("success");
      setKeyInput("");
      onKeyAdded?.();
      setTimeout(() => setStatus("idle"), 2000);
    } catch (err) {
      setStatus("error");
      setErrorMsg(err instanceof Error ? err.message : "Failed to save key");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle className="text-sm">{meta.label}</CardTitle>
            <CardDescription className="text-xs mt-0.5">
              {meta.description}
            </CardDescription>
          </div>
          <div className="flex flex-col items-end gap-1">
            {meta.authType === "none" ? (
              <Badge variant="secondary" className="text-[10px]">
                Local
              </Badge>
            ) : (
              <Badge
                variant={hasKeys ? "default" : "destructive"}
                className="text-[10px]"
              >
                {hasKeys ? "Configured" : "No Key"}
              </Badge>
            )}
            <Badge
              variant={healthy ? "default" : "outline"}
              className="text-[10px]"
            >
              {healthy ? "Online" : "Offline"}
            </Badge>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {/* Auth type indicator */}
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {meta.authType === "api-key" && (
            <>
              <Key className="size-3" />
              <span>API Key authentication</span>
            </>
          )}
          {meta.authType === "oauth" && (
            <>
              <Shield className="size-3" />
              <span>OAuth authentication</span>
            </>
          )}
          {meta.authType === "none" && (
            <>
              <Globe className="size-3" />
              <span>No authentication required</span>
            </>
          )}
        </div>

        {/* API key input for cloud providers */}
        {meta.authType === "api-key" && (
          <div className="space-y-2">
            <div className="flex gap-2">
              <Input
                type="password"
                placeholder={meta.keyPlaceholder}
                value={keyInput}
                onChange={(e) => setKeyInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void handleSave();
                }}
                className="h-8 text-xs font-mono flex-1"
                autoComplete="off"
              />
              <Button
                size="sm"
                onClick={() => void handleSave()}
                disabled={saving || !keyInput.trim()}
                className="h-8"
              >
                {saving ? "Saving..." : "Add Key"}
              </Button>
            </div>

            {status === "success" && (
              <p className="flex items-center gap-1 text-xs text-green-500">
                <CheckCircle2 className="size-3" />
                Key saved successfully
              </p>
            )}
            {status === "error" && (
              <p className="flex items-center gap-1 text-xs text-destructive">
                <AlertCircle className="size-3" />
                {errorMsg}
              </p>
            )}

            {meta.docsUrl && (
              <a
                href={meta.docsUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-[10px] text-blue-400 hover:underline"
              >
                <ExternalLink className="size-2.5" />
                Get API key from {meta.label.split("(")[0].trim()}
              </a>
            )}
          </div>
        )}

        {/* Local provider — just show status */}
        {meta.authType === "none" && (
          <p className="text-[10px] text-muted-foreground">
            {healthy
              ? "Running locally. No configuration needed."
              : "Not detected. Ensure the service is running."}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
