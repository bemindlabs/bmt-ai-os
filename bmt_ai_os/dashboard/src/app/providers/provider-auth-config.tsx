"use client";

import { useState, useEffect, useCallback } from "react";
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
  Loader2,
  LogIn,
  Hash,
  Clock,
} from "lucide-react";
import {
  addProviderKey,
  oauthStart,
  oauthStatus,
  type OAuthStatusResponse,
  type CredentialType,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Provider metadata — auth types, docs links, key formats
// ---------------------------------------------------------------------------

type AuthType = "api-key" | "oauth" | "token" | "none";

interface ProviderAuthMeta {
  label: string;
  authTypes: AuthType[];
  docsUrl: string;
  keyPlaceholder: string;
  keyPrefix?: string;
  description: string;
  oauthProvider?: string;
  tokenPlaceholder?: string;
}

const PROVIDER_AUTH_META: Record<string, ProviderAuthMeta> = {
  anthropic: {
    label: "Anthropic (Claude)",
    authTypes: ["api-key"],
    docsUrl: "https://console.anthropic.com/settings/keys",
    keyPlaceholder: "sk-ant-api03-...",
    keyPrefix: "sk-ant-",
    description:
      "Claude models (Sonnet, Opus, Haiku). API key from Anthropic Console.",
  },
  openai: {
    label: "OpenAI (GPT / Codex)",
    authTypes: ["api-key", "oauth"],
    docsUrl: "https://platform.openai.com/api-keys",
    keyPlaceholder: "sk-proj-...",
    keyPrefix: "sk-",
    description:
      "GPT-4o, GPT-4, o1, Codex models. API key or OAuth from OpenAI Platform.",
    oauthProvider: "openai",
  },
  gemini: {
    label: "Google (Gemini)",
    authTypes: ["api-key", "oauth"],
    docsUrl: "https://aistudio.google.com/apikey",
    keyPlaceholder: "AIza...",
    keyPrefix: "AIza",
    description:
      "Gemini Pro, Gemini Flash models. API key or OAuth from Google AI Studio.",
    oauthProvider: "gemini",
  },
  groq: {
    label: "Groq",
    authTypes: ["api-key"],
    docsUrl: "https://console.groq.com/keys",
    keyPlaceholder: "gsk_...",
    keyPrefix: "gsk_",
    description: "Fast inference for Llama, Mixtral. API key from Groq Console.",
  },
  mistral: {
    label: "Mistral AI",
    authTypes: ["api-key"],
    docsUrl: "https://console.mistral.ai/api-keys",
    keyPlaceholder: "...",
    description:
      "Mistral, Mixtral, Codestral models. API key from Mistral Console.",
  },
  ollama: {
    label: "Ollama (Local)",
    authTypes: ["none"],
    docsUrl: "https://ollama.com",
    keyPlaceholder: "",
    description: "Local LLM inference. No API key required — runs on device.",
  },
  vllm: {
    label: "vLLM (Local)",
    authTypes: ["none", "token"],
    docsUrl: "https://docs.vllm.ai",
    keyPlaceholder: "",
    description: "High-throughput local inference. Optional bearer token.",
    tokenPlaceholder: "Bearer token...",
  },
  llamacpp: {
    label: "llama.cpp (Local)",
    authTypes: ["none", "token"],
    docsUrl: "https://github.com/ggerganov/llama.cpp",
    keyPlaceholder: "",
    description: "CPU/GPU inference via llama.cpp server. Optional bearer token.",
    tokenPlaceholder: "Bearer token...",
  },
};

function getAuthMeta(providerName: string): ProviderAuthMeta {
  return (
    PROVIDER_AUTH_META[providerName.toLowerCase()] ?? {
      label: providerName,
      authTypes: ["api-key"],
      docsUrl: "",
      keyPlaceholder: "API key...",
      description: `${providerName} provider.`,
    }
  );
}

// ---------------------------------------------------------------------------
// Auth method tab selector
// ---------------------------------------------------------------------------

function AuthMethodTabs({
  methods,
  active,
  onSelect,
}: {
  methods: AuthType[];
  active: AuthType;
  onSelect: (m: AuthType) => void;
}) {
  const filtered = methods.filter((m) => m !== "none");
  if (filtered.length <= 1) return null;

  const labels: Record<AuthType, { icon: typeof Key; text: string }> = {
    "api-key": { icon: Key, text: "API Key" },
    oauth: { icon: Shield, text: "OAuth" },
    token: { icon: Hash, text: "Token" },
    none: { icon: Globe, text: "None" },
  };

  return (
    <div className="flex gap-1 rounded-lg bg-muted p-0.5">
      {filtered.map((m) => {
        const { icon: Icon, text } = labels[m];
        const isActive = active === m;
        return (
          <button
            key={m}
            onClick={() => onSelect(m)}
            className={`flex items-center gap-1 rounded-md px-2 py-1 text-[10px] font-medium transition-colors ${
              isActive
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Icon className="size-2.5" />
            {text}
          </button>
        );
      })}
    </div>
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
  const hasOnlyNone = meta.authTypes.length === 1 && meta.authTypes[0] === "none";
  const defaultMethod = hasOnlyNone
    ? "none"
    : meta.authTypes.find((m) => m !== "none") ?? "api-key";

  const [activeMethod, setActiveMethod] = useState<AuthType>(defaultMethod);
  const [keyInput, setKeyInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<"idle" | "success" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState("");

  // OAuth state
  const [oauthInfo, setOauthInfo] = useState<OAuthStatusResponse | null>(null);
  const [oauthLoading, setOauthLoading] = useState(false);
  const [oauthClientId, setOauthClientId] = useState("");
  const [oauthClientSecret, setOauthClientSecret] = useState("");

  const loadOauthStatus = useCallback(async () => {
    if (!meta.oauthProvider) return;
    try {
      const info = await oauthStatus(providerName);
      setOauthInfo(info);
    } catch {
      // OAuth status check is best-effort
    }
  }, [providerName, meta.oauthProvider]);

  useEffect(() => {
    if (meta.authTypes.includes("oauth")) {
      void loadOauthStatus();
    }
  }, [meta.authTypes, loadOauthStatus]);

  async function handleSaveKey() {
    if (!keyInput.trim()) return;
    setSaving(true);
    setStatus("idle");
    try {
      const credType: CredentialType =
        activeMethod === "token" ? "token" : "api_key";
      await addProviderKey(providerName, keyInput.trim(), credType);
      setStatus("success");
      setKeyInput("");
      onKeyAdded?.();
      setTimeout(() => setStatus("idle"), 2000);
    } catch (err) {
      setStatus("error");
      setErrorMsg(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function handleOAuthConnect() {
    setOauthLoading(true);
    setStatus("idle");
    try {
      const redirectUri = `${window.location.origin}/oauth/callback`;
      const result = await oauthStart(
        providerName,
        redirectUri,
        oauthClientId || undefined,
        oauthClientSecret || undefined,
      );
      // Store provider + CSRF state nonce in sessionStorage for callback verification
      // (state is a non-secret CSRF token, not credentials — standard OAuth 2.0 practice)
      sessionStorage.setItem("bmt_oauth_provider", providerName);
      sessionStorage.setItem("bmt_oauth_state", result.state);
      // Redirect to the OAuth provider
      window.location.href = result.auth_url;
    } catch (err) {
      setStatus("error");
      setErrorMsg(err instanceof Error ? err.message : "OAuth failed");
      setOauthLoading(false);
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
            {hasOnlyNone ? (
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
        {/* Auth method tabs */}
        <AuthMethodTabs
          methods={meta.authTypes}
          active={activeMethod}
          onSelect={setActiveMethod}
        />

        {/* API key input */}
        {activeMethod === "api-key" && (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Key className="size-3" />
              <span>API Key authentication</span>
            </div>
            <div className="flex gap-2">
              <Input
                type="password"
                placeholder={meta.keyPlaceholder}
                value={keyInput}
                onChange={(e) => setKeyInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void handleSaveKey();
                }}
                className="h-8 text-xs font-mono flex-1"
                autoComplete="off"
              />
              <Button
                size="sm"
                onClick={() => void handleSaveKey()}
                disabled={saving || !keyInput.trim()}
                className="h-8"
              >
                {saving ? "Saving..." : "Add Key"}
              </Button>
            </div>

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

        {/* OAuth connect */}
        {activeMethod === "oauth" && (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Shield className="size-3" />
              <span>OAuth 2.0 authentication (PKCE)</span>
            </div>

            {/* OAuth status */}
            {oauthInfo?.oauth_valid && (
              <div className="flex items-center gap-2 rounded-md border border-green-500/30 bg-green-500/5 px-3 py-2">
                <CheckCircle2 className="size-3.5 text-green-500" />
                <div className="flex-1 text-xs">
                  <span className="font-medium text-green-500">
                    OAuth Connected
                  </span>
                  {oauthInfo.credentials[0]?.display_name && (
                    <span className="ml-1.5 text-muted-foreground">
                      ({oauthInfo.credentials[0].display_name})
                    </span>
                  )}
                </div>
                {oauthInfo.credentials[0]?.expires_at && (
                  <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
                    <Clock className="size-2.5" />
                    Expires{" "}
                    {new Date(
                      oauthInfo.credentials[0].expires_at * 1000,
                    ).toLocaleString()}
                  </span>
                )}
              </div>
            )}

            {/* Client ID / Secret fields (if no env config) */}
            {oauthInfo && !oauthInfo.has_client_config && (
              <div className="space-y-2">
                <p className="text-[10px] text-muted-foreground">
                  OAuth client credentials not found in environment. Enter them
                  below or set the environment variables on the controller.
                </p>
                <Input
                  type="text"
                  placeholder="OAuth Client ID"
                  value={oauthClientId}
                  onChange={(e) => setOauthClientId(e.target.value)}
                  className="h-8 text-xs font-mono"
                  autoComplete="off"
                />
                <Input
                  type="password"
                  placeholder="OAuth Client Secret"
                  value={oauthClientSecret}
                  onChange={(e) => setOauthClientSecret(e.target.value)}
                  className="h-8 text-xs font-mono"
                  autoComplete="off"
                />
              </div>
            )}

            <Button
              size="sm"
              variant={oauthInfo?.oauth_valid ? "outline" : "default"}
              onClick={() => void handleOAuthConnect()}
              disabled={
                oauthLoading ||
                (!oauthInfo?.has_client_config && !oauthClientId.trim())
              }
              className="h-8 w-full"
            >
              {oauthLoading ? (
                <>
                  <Loader2 className="size-3.5 animate-spin mr-1.5" />
                  Connecting...
                </>
              ) : (
                <>
                  <LogIn className="size-3.5 mr-1.5" />
                  {oauthInfo?.oauth_valid
                    ? "Reconnect OAuth"
                    : "Connect with OAuth"}
                </>
              )}
            </Button>
          </div>
        )}

        {/* Token / Bearer token input */}
        {activeMethod === "token" && (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Hash className="size-3" />
              <span>Bearer token / Personal access token</span>
            </div>
            <div className="flex gap-2">
              <Input
                type="password"
                placeholder={meta.tokenPlaceholder ?? "Bearer token..."}
                value={keyInput}
                onChange={(e) => setKeyInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void handleSaveKey();
                }}
                className="h-8 text-xs font-mono flex-1"
                autoComplete="off"
              />
              <Button
                size="sm"
                onClick={() => void handleSaveKey()}
                disabled={saving || !keyInput.trim()}
                className="h-8"
              >
                {saving ? "Saving..." : "Add Token"}
              </Button>
            </div>
            <p className="text-[10px] text-muted-foreground">
              Static bearer token — not automatically refreshed.
            </p>
          </div>
        )}

        {/* Status feedback */}
        {status === "success" && (
          <p className="flex items-center gap-1 text-xs text-green-500">
            <CheckCircle2 className="size-3" />
            Credential saved successfully
          </p>
        )}
        {status === "error" && (
          <p className="flex items-center gap-1 text-xs text-destructive">
            <AlertCircle className="size-3" />
            {errorMsg}
          </p>
        )}

        {/* Local provider — just show status */}
        {hasOnlyNone && (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Globe className="size-3" />
              <span>No authentication required</span>
            </div>
            <p className="text-[10px] text-muted-foreground">
              {healthy
                ? "Running locally. No configuration needed."
                : "Not detected. Ensure the service is running."}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
