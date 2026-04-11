"use client";

import { useEffect, useState, useCallback } from "react";
import {
  fetchProviders,
  fetchProviderConfigs,
  setActiveProvider,
  createProviderConfig,
  updateProviderConfig,
  deleteProviderConfig,
  testProviderConnection,
  PROVIDER_DEFAULT_URLS,
  type ProviderConfig,
  type ProviderConfigIn,
  type ProviderType,
  type ProviderTestResult,
} from "@/lib/api";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PROVIDER_TYPES: ProviderType[] = [
  "ollama",
  "openai",
  "anthropic",
  "gemini",
  "groq",
  "mistral",
  "vllm",
  "llamacpp",
];

// ---------------------------------------------------------------------------
// Provider form (shared between Add and Edit)
// ---------------------------------------------------------------------------

interface ProviderFormState {
  name: string;
  provider_type: ProviderType;
  base_url: string;
  api_key: string;
  default_model: string;
  enabled: boolean;
}

const DEFAULT_FORM: ProviderFormState = {
  name: "",
  provider_type: "ollama",
  base_url: PROVIDER_DEFAULT_URLS.ollama,
  api_key: "",
  default_model: "",
  enabled: true,
};

interface ProviderFormProps {
  initial?: ProviderFormState;
  isEdit?: boolean;
  onSubmit: (data: ProviderFormState) => Promise<void>;
  onCancel: () => void;
}

function ProviderForm({ initial, isEdit, onSubmit, onCancel }: ProviderFormProps) {
  const [form, setForm] = useState<ProviderFormState>(initial ?? DEFAULT_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<ProviderTestResult | null>(null);
  const [testing, setTesting] = useState(false);

  function handleTypeChange(type: ProviderType) {
    setForm((prev) => ({
      ...prev,
      provider_type: type,
      // Only auto-fill base_url when it hasn't been customised from the default
      base_url:
        !prev.base_url ||
        Object.values(PROVIDER_DEFAULT_URLS).includes(prev.base_url)
          ? PROVIDER_DEFAULT_URLS[type]
          : prev.base_url,
    }));
  }

  async function handleTestConnection() {
    if (!form.name) {
      setError("Enter a provider name first to test the connection.");
      return;
    }
    setTesting(true);
    setTestResult(null);
    try {
      const result = await testProviderConnection(form.name);
      setTestResult(result);
    } catch (e) {
      setTestResult({
        name: form.name,
        healthy: false,
        latency_ms: 0,
        error: e instanceof Error ? e.message : "Unknown error",
      });
    } finally {
      setTesting(false);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await onSubmit(form);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save provider.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {!isEdit && (
        <div className="space-y-1">
          <label className="text-xs font-medium text-muted-foreground">Name</label>
          <Input
            required
            placeholder="my-openai"
            value={form.name}
            onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))}
          />
        </div>
      )}

      <div className="space-y-1">
        <label className="text-xs font-medium text-muted-foreground">Type</label>
        <select
          className="flex h-8 w-full rounded-lg border border-input bg-background px-3 py-1 text-sm text-foreground outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50"
          value={form.provider_type}
          onChange={(e) => handleTypeChange(e.target.value as ProviderType)}
          disabled={isEdit}
        >
          {PROVIDER_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>

      <div className="space-y-1">
        <label className="text-xs font-medium text-muted-foreground">Base URL</label>
        <Input
          placeholder={PROVIDER_DEFAULT_URLS[form.provider_type]}
          value={form.base_url}
          onChange={(e) => setForm((p) => ({ ...p, base_url: e.target.value }))}
        />
      </div>

      <div className="space-y-1">
        <label className="text-xs font-medium text-muted-foreground">API Key</label>
        <Input
          type="password"
          placeholder="sk-…"
          value={form.api_key}
          onChange={(e) => setForm((p) => ({ ...p, api_key: e.target.value }))}
          autoComplete="off"
        />
      </div>

      <div className="space-y-1">
        <label className="text-xs font-medium text-muted-foreground">Default Model</label>
        <Input
          placeholder="e.g. gpt-4o or qwen2.5-coder:7b"
          value={form.default_model}
          onChange={(e) => setForm((p) => ({ ...p, default_model: e.target.value }))}
        />
      </div>

      <div className="flex items-center gap-2">
        <Switch
          checked={form.enabled}
          onCheckedChange={(v) => setForm((p) => ({ ...p, enabled: !!v }))}
        />
        <span className="text-sm text-muted-foreground">Enabled</span>
      </div>

      {error && <p className="text-xs text-destructive">{error}</p>}

      {testResult && (
        <p
          className={
            testResult.healthy
              ? "text-xs text-green-600 dark:text-green-400"
              : "text-xs text-destructive"
          }
        >
          {testResult.healthy
            ? `Connection OK (${testResult.latency_ms.toFixed(0)} ms)`
            : `Connection failed: ${testResult.error ?? "unknown error"}`}
        </p>
      )}

      <div className="flex gap-2 flex-wrap">
        <Button type="submit" size="sm" disabled={submitting}>
          {submitting ? "Saving…" : isEdit ? "Save Changes" : "Add Provider"}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={handleTestConnection}
          disabled={testing}
        >
          {testing ? "Testing…" : "Test Connection"}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Delete confirmation dialog
// ---------------------------------------------------------------------------

interface DeleteDialogProps {
  name: string;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
}

function DeleteDialog({ name, onConfirm, onCancel }: DeleteDialogProps) {
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleConfirm() {
    setDeleting(true);
    setError(null);
    try {
      await onConfirm();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed.");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm">
        Are you sure you want to remove <strong>{name}</strong>? This cannot be undone.
      </p>
      {error && <p className="text-xs text-destructive">{error}</p>}
      <div className="flex gap-2">
        <Button size="sm" variant="destructive" onClick={handleConfirm} disabled={deleting}>
          {deleting ? "Deleting…" : "Delete"}
        </Button>
        <Button size="sm" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Provider card
// ---------------------------------------------------------------------------

interface ProviderCardProps {
  config: ProviderConfig;
  isActive: boolean;
  onUpdated: () => void;
}

function ProviderCard({ config, isActive, onUpdated }: ProviderCardProps) {
  const [mode, setMode] = useState<"view" | "edit" | "delete">("view");
  const [toggling, setToggling] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [switchMsg, setSwitchMsg] = useState<"idle" | "success" | "error">("idle");
  const [testResult, setTestResult] = useState<ProviderTestResult | null>(null);
  const [testing, setTesting] = useState(false);

  async function handleToggle() {
    setToggling(true);
    try {
      await updateProviderConfig(config.name, { enabled: !config.enabled });
      onUpdated();
    } finally {
      setToggling(false);
    }
  }

  async function handleSetActive() {
    setSwitching(true);
    setSwitchMsg("idle");
    try {
      await setActiveProvider(config.name);
      setSwitchMsg("success");
      onUpdated();
    } catch {
      setSwitchMsg("error");
    } finally {
      setSwitching(false);
    }
  }

  async function handleTestConnection() {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await testProviderConnection(config.name);
      setTestResult(result);
    } catch (e) {
      setTestResult({
        name: config.name,
        healthy: false,
        latency_ms: 0,
        error: e instanceof Error ? e.message : "Unknown error",
      });
    } finally {
      setTesting(false);
    }
  }

  if (mode === "edit") {
    const initial: ProviderFormState = {
      name: config.name,
      provider_type: config.provider_type,
      base_url: config.base_url,
      api_key: "",
      default_model: config.default_model,
      enabled: config.enabled,
    };

    return (
      <Card>
        <CardHeader>
          <CardTitle className="capitalize text-base">{config.name}</CardTitle>
          <CardDescription>Editing provider configuration</CardDescription>
        </CardHeader>
        <CardContent>
          <ProviderForm
            initial={initial}
            isEdit
            onSubmit={async (data) => {
              await updateProviderConfig(config.name, {
                base_url: data.base_url,
                api_key: data.api_key || undefined,
                default_model: data.default_model,
                enabled: data.enabled,
              });
              setMode("view");
              onUpdated();
            }}
            onCancel={() => setMode("view")}
          />
        </CardContent>
      </Card>
    );
  }

  if (mode === "delete") {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="capitalize text-base">{config.name}</CardTitle>
          <CardDescription>Confirm deletion</CardDescription>
        </CardHeader>
        <CardContent>
          <DeleteDialog
            name={config.name}
            onConfirm={async () => {
              await deleteProviderConfig(config.name);
              onUpdated();
            }}
            onCancel={() => setMode("view")}
          />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="capitalize text-base">{config.name}</CardTitle>
          <div className="flex flex-col items-end gap-1">
            <Badge variant={config.enabled ? "default" : "secondary"}>
              {config.enabled ? "enabled" : "disabled"}
            </Badge>
            {isActive && <Badge variant="secondary">active</Badge>}
          </div>
        </div>
        <CardDescription className="font-mono text-xs truncate">
          {config.provider_type}
          {config.base_url ? ` · ${config.base_url}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {config.default_model && (
          <p className="text-xs text-muted-foreground">
            Model: <span className="font-mono">{config.default_model}</span>
          </p>
        )}

        {testResult && (
          <p
            className={
              testResult.healthy
                ? "text-xs text-green-600 dark:text-green-400"
                : "text-xs text-destructive"
            }
          >
            {testResult.healthy
              ? `Connection OK (${testResult.latency_ms.toFixed(0)} ms)`
              : `Failed: ${testResult.error ?? "unknown"}`}
          </p>
        )}

        <div className="flex items-center gap-2 flex-wrap">
          {/* Enable/disable toggle */}
          <div className="flex items-center gap-1.5">
            <Switch
              checked={config.enabled}
              onCheckedChange={() => { handleToggle(); }}
              disabled={toggling}
              size="sm"
            />
            <span className="text-xs text-muted-foreground">
              {toggling ? "…" : config.enabled ? "On" : "Off"}
            </span>
          </div>

          {/* Set active */}
          {!isActive && config.enabled && (
            <Button
              size="xs"
              variant="outline"
              onClick={handleSetActive}
              disabled={switching}
            >
              {switching ? "Switching…" : "Set Active"}
            </Button>
          )}

          {/* Test connection */}
          <Button
            size="xs"
            variant="outline"
            onClick={handleTestConnection}
            disabled={testing}
          >
            {testing ? "Testing…" : "Test"}
          </Button>

          {/* Edit */}
          <Button size="xs" variant="outline" onClick={() => setMode("edit")}>
            Edit
          </Button>

          {/* Delete */}
          <Button size="xs" variant="destructive" onClick={() => setMode("delete")}>
            Delete
          </Button>
        </div>

        {switchMsg === "success" && (
          <p className="text-xs text-muted-foreground">Switched. Reload to confirm.</p>
        )}
        {switchMsg === "error" && (
          <p className="text-xs text-destructive">Failed to switch active provider.</p>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function ProvidersPage() {
  const [configs, setConfigs] = useState<ProviderConfig[]>([]);
  const [activeProvider, setActiveProviderName] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showAddForm, setShowAddForm] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [cfgResult, liveResult] = await Promise.allSettled([
        fetchProviderConfigs(),
        fetchProviders(),
      ]);

      if (cfgResult.status === "fulfilled") {
        setConfigs(cfgResult.value.providers);
      }
      if (liveResult.status === "fulfilled") {
        setActiveProviderName(liveResult.value.active ?? null);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  async function handleAdd(data: {
    name: string;
    provider_type: ProviderType;
    base_url: string;
    api_key: string;
    default_model: string;
    enabled: boolean;
  }) {
    setAddError(null);
    const payload: ProviderConfigIn = {
      name: data.name,
      provider_type: data.provider_type,
      base_url: data.base_url || undefined,
      api_key: data.api_key || undefined,
      default_model: data.default_model || undefined,
      enabled: data.enabled,
    };
    await createProviderConfig(payload);
    setShowAddForm(false);
    await reload();
  }

  return (
    <div className="space-y-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Providers</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Manage and configure LLM inference providers.
          </p>
        </div>
        <Button size="sm" onClick={() => { setShowAddForm((v) => !v); setAddError(null); }}>
          {showAddForm ? "Cancel" : "Add Provider"}
        </Button>
      </div>

      {showAddForm && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Add New Provider</CardTitle>
            <CardDescription>
              Configure a new LLM backend and register it with the controller.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {addError && <p className="mb-3 text-xs text-destructive">{addError}</p>}
            <ProviderForm
              onSubmit={handleAdd}
              onCancel={() => { setShowAddForm(false); setAddError(null); }}
            />
          </CardContent>
        </Card>
      )}

      {loading && configs.length === 0 && (
        <Card>
          <CardContent className="pt-4">
            <p className="text-sm text-muted-foreground">Loading providers…</p>
          </CardContent>
        </Card>
      )}

      {!loading && configs.length === 0 && !showAddForm && (
        <Card>
          <CardContent className="pt-4">
            <p className="text-sm text-muted-foreground">
              No providers configured yet. Click{" "}
              <button
                className="underline"
                onClick={() => setShowAddForm(true)}
              >
                Add Provider
              </button>{" "}
              to get started.
            </p>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {configs.map((cfg) => (
          <ProviderCard
            key={cfg.name}
            config={cfg}
            isActive={cfg.name === activeProvider}
            onUpdated={reload}
          />
        ))}
      </div>
    </div>
  );
}
