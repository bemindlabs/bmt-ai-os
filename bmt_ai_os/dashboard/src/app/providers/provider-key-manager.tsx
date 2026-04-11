"use client";

import { useState, useCallback } from "react";
import {
  fetchProviderKeys,
  addProviderKey,
  deleteProviderKey,
  type ProviderKey,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";

interface ProviderKeyManagerProps {
  providerName: string;
}

function formatTimestamp(ts: number | null): string {
  if (ts === null) return "Never";
  return new Date(ts * 1000).toLocaleString();
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
          <Badge
            variant={keyEntry.status === "active" ? "default" : "destructive"}
            className="text-xs"
          >
            {keyEntry.status}
          </Badge>
        </div>
        <div className="flex gap-4 text-xs text-muted-foreground">
          <span>Requests: {keyEntry.usage_count}</span>
          <span>Last used: {formatTimestamp(keyEntry.last_used)}</span>
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
          {deleting ? "Removing…" : "Remove"}
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
      const result = await addProviderKey(providerName, newKey.trim());
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

  return (
    <div className="mt-3 border-t pt-3">
      <button
        type="button"
        onClick={handleToggle}
        className="flex w-full items-center justify-between text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
      >
        <span>API Keys ({expanded ? keys.length : "…"})</span>
        <span>{expanded ? "▲" : "▼"}</span>
      </button>

      {expanded && (
        <div className="mt-3 space-y-3">
          {loading && (
            <p className="text-xs text-muted-foreground">Loading keys…</p>
          )}
          {loadError && (
            <p className="text-xs text-destructive">{loadError}</p>
          )}

          {!loading && keys.length === 0 && !loadError && (
            <p className="text-xs text-muted-foreground">
              No keys configured. Add one below.
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

          {/* Add key form */}
          <div className="flex gap-2">
            <Input
              type="password"
              placeholder="Paste API key…"
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
              {adding ? "Adding…" : "Add"}
            </Button>
          </div>
          {addError && (
            <p className="text-xs text-destructive">{addError}</p>
          )}
        </div>
      )}
    </div>
  );
}
