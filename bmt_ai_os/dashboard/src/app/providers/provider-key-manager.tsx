"use client";

import { useState, useCallback } from "react";
import {
  fetchProviderKeys,
  addProviderKey,
  deleteProviderKey,
  type ProviderKey,
  type CredentialType,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Key, Shield, Hash, Clock } from "lucide-react";

interface ProviderKeyManagerProps {
  providerName: string;
}

function formatTimestamp(ts: number | null): string {
  if (ts === null) return "Never";
  return new Date(ts * 1000).toLocaleString();
}

const CREDENTIAL_TYPE_META: Record<
  string,
  { label: string; icon: typeof Key; variant: "default" | "secondary" | "outline" }
> = {
  api_key: { label: "API Key", icon: Key, variant: "secondary" },
  oauth: { label: "OAuth", icon: Shield, variant: "default" },
  token: { label: "Token", icon: Hash, variant: "outline" },
};

function CredentialTypeBadge({ type }: { type: string }) {
  const meta = CREDENTIAL_TYPE_META[type] ?? CREDENTIAL_TYPE_META.api_key;
  const Icon = meta.icon;
  return (
    <Badge variant={meta.variant} className="text-[10px] gap-0.5 px-1.5">
      <Icon className="size-2.5" />
      {meta.label}
    </Badge>
  );
}

function KeyRow({
  providerName,
  keyEntry,
  onDeleted,
}: {
  providerName: string;
  keyEntry: ProviderKey;
  onDeleted: () => void;
}) {
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleDelete() {
    setDeleting(true);
    setError(null);
    try {
      await deleteProviderKey(providerName, keyEntry.id);
      onDeleted();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm">
      <div className="min-w-0 flex-1 space-y-0.5">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs text-muted-foreground">
            {keyEntry.masked_key}
          </span>
          <CredentialTypeBadge type={keyEntry.credential_type ?? "api_key"} />
          <Badge
            variant={
              keyEntry.status === "active"
                ? "default"
                : keyEntry.status === "expired"
                  ? "outline"
                  : "destructive"
            }
            className="text-xs"
          >
            {keyEntry.status}
          </Badge>
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-muted-foreground">
          {keyEntry.display_name && (
            <span className="font-medium">{keyEntry.display_name}</span>
          )}
          <span>Requests: {keyEntry.usage_count}</span>
          <span>Last used: {formatTimestamp(keyEntry.last_used)}</span>
          {keyEntry.expires_at != null && (
            <span className="flex items-center gap-1">
              <Clock className="size-2.5" />
              Expires: {formatTimestamp(keyEntry.expires_at)}
            </span>
          )}
          {keyEntry.last_error && (
            <span className="text-destructive truncate">
              Error: {keyEntry.last_error}
            </span>
          )}
          {keyEntry.cooldown_until !== null && keyEntry.status === "cooldown" && (
            <span className="text-amber-500">
              Cooldown until: {formatTimestamp(keyEntry.cooldown_until)}
            </span>
          )}
        </div>
      </div>
      <div className="shrink-0 space-y-1">
        <Button
          size="sm"
          variant="destructive"
          onClick={handleDelete}
          disabled={deleting}
        >
          {deleting ? "Removing\u2026" : "Remove"}
        </Button>
        {error && (
          <p className="text-xs text-destructive text-right">{error}</p>
        )}
      </div>
    </div>
  );
}

export function ProviderKeyManager({ providerName }: ProviderKeyManagerProps) {
  const [expanded, setExpanded] = useState(false);
  const [keys, setKeys] = useState<ProviderKey[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [newKey, setNewKey] = useState("");
  const [newKeyType, setNewKeyType] = useState<CredentialType>("api_key");
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  const loadKeys = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const result = await fetchProviderKeys(providerName);
      setKeys(result.keys);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Failed to load keys");
    } finally {
      setLoading(false);
    }
  }, [providerName]);

  function handleToggle() {
    if (!expanded) {
      void loadKeys();
    }
    setExpanded((prev) => !prev);
  }

  async function handleAddKey() {
    if (!newKey.trim()) return;
    setAdding(true);
    setAddError(null);
    try {
      const result = await addProviderKey(providerName, newKey.trim(), newKeyType);
      setKeys((prev) => [...prev, result.key]);
      setNewKey("");
    } catch (err) {
      setAddError(err instanceof Error ? err.message : "Failed to add key");
    } finally {
      setAdding(false);
    }
  }

  function handleKeyDeleted(keyId: string) {
    setKeys((prev) => prev.filter((k) => k.id !== keyId));
  }

  // Group keys by credential type for summary
  const keySummary = keys.reduce<Record<string, number>>((acc, k) => {
    const t = k.credential_type ?? "api_key";
    acc[t] = (acc[t] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="mt-3 border-t pt-3">
      <button
        type="button"
        onClick={handleToggle}
        className="flex w-full items-center justify-between text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
      >
        <span>
          Credentials{" "}
          {expanded ? (
            <span className="text-[10px]">
              ({keys.length} total
              {Object.entries(keySummary).map(([type, count]) => (
                <span key={type}>
                  {" \u00B7 "}
                  {count} {type.replace("_", " ")}
                </span>
              ))}
              )
            </span>
          ) : (
            "(…)"
          )}
        </span>
        <span>{expanded ? "\u25B2" : "\u25BC"}</span>
      </button>

      {expanded && (
        <div className="mt-3 space-y-3">
          {loading && (
            <p className="text-xs text-muted-foreground">Loading credentials\u2026</p>
          )}
          {loadError && (
            <p className="text-xs text-destructive">{loadError}</p>
          )}

          {!loading && keys.length === 0 && !loadError && (
            <p className="text-xs text-muted-foreground">
              No credentials configured. Add one below.
            </p>
          )}

          {keys.map((k) => (
            <KeyRow
              key={k.id}
              providerName={providerName}
              keyEntry={k}
              onDeleted={() => handleKeyDeleted(k.id)}
            />
          ))}

          {/* Add credential form */}
          <div className="space-y-2">
            <div className="flex gap-1">
              {(["api_key", "token"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setNewKeyType(t)}
                  className={`rounded-md px-2 py-0.5 text-[10px] font-medium transition-colors ${
                    newKeyType === t
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {t === "api_key" ? "API Key" : "Token"}
                </button>
              ))}
            </div>
            <div className="flex gap-2">
              <Input
                type="password"
                placeholder={
                  newKeyType === "token"
                    ? "Paste bearer token\u2026"
                    : "Paste API key\u2026"
                }
                value={newKey}
                onChange={(e) => setNewKey(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void handleAddKey();
                }}
                className="h-8 text-xs font-mono"
              />
              <Button
                size="sm"
                onClick={handleAddKey}
                disabled={adding || !newKey.trim()}
              >
                {adding ? "Adding\u2026" : "Add"}
              </Button>
            </div>
            {addError && (
              <p className="text-xs text-destructive">{addError}</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
