"use client";

import { useEffect, useRef, useState } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Separator } from "@/components/ui/separator";
import { Plus, Trash2, Key, Upload } from "lucide-react";
import { fetchSshKeys, uploadSshKey, deleteSshKey, SshKeySummary } from "@/lib/api";

export function SshKeyManager() {
  const [keys, setKeys] = useState<SshKeySummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Upload form state
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [keyContent, setKeyContent] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchSshKeys();
      setKeys(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch SSH keys");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    setUploadError(null);

    const trimmedName = name.trim();
    const trimmedKey = keyContent.trim();

    if (!trimmedName) {
      setUploadError("Key name is required.");
      return;
    }
    if (!trimmedKey) {
      setUploadError("Key content is required.");
      return;
    }

    setUploading(true);
    try {
      await uploadSshKey(trimmedName, trimmedKey);
      setName("");
      setKeyContent("");
      setShowForm(false);
      await load();
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(keyName: string) {
    if (!confirm(`Delete SSH key "${keyName}"?`)) return;
    try {
      await deleteSshKey(keyName);
      setKeys((prev) => prev.filter((k) => k.name !== keyName));
    } catch (err) {
      alert(err instanceof Error ? err.message : "Delete failed");
    }
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      setKeyContent((ev.target?.result as string) ?? "");
    };
    reader.readAsText(file);
  }

  function formatDate(iso: string): string {
    try {
      return new Date(iso).toLocaleString();
    } catch {
      return iso;
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>SSH Keys</CardTitle>
            <CardDescription>
              Manage private keys used for fleet device SSH connections.
            </CardDescription>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowForm((v) => !v)}
          >
            <Plus className="mr-1.5 size-4" />
            Add Key
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Upload form */}
        {showForm && (
          <form onSubmit={handleUpload} className="space-y-3 rounded-lg border border-dashed p-4">
            <p className="text-sm font-medium">Upload SSH Private Key</p>

            <div className="space-y-1.5">
              <label className="text-xs text-muted-foreground">Key Name</label>
              <Input
                placeholder="e.g. jetson-orin-1"
                value={name}
                onChange={(e) => setName(e.target.value)}
                disabled={uploading}
                required
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs text-muted-foreground">Private Key Content (PEM)</label>
              <textarea
                className="h-32 w-full resize-none rounded-md border border-input bg-background px-3 py-2 font-mono text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
                placeholder="-----BEGIN OPENSSH PRIVATE KEY-----&#10;...&#10;-----END OPENSSH PRIVATE KEY-----"
                value={keyContent}
                onChange={(e) => setKeyContent(e.target.value)}
                disabled={uploading}
              />
            </div>

            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => fileRef.current?.click()}
                disabled={uploading}
              >
                <Upload className="mr-1.5 size-3.5" />
                Load from file
              </Button>
              <input
                ref={fileRef}
                type="file"
                accept=".pem,.key,*"
                className="hidden"
                onChange={handleFileChange}
              />
            </div>

            {uploadError && (
              <p className="text-xs text-red-500">{uploadError}</p>
            )}

            <div className="flex items-center gap-2">
              <Button type="submit" size="sm" disabled={uploading}>
                {uploading ? "Uploading…" : "Upload Key"}
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  setShowForm(false);
                  setUploadError(null);
                  setName("");
                  setKeyContent("");
                }}
                disabled={uploading}
              >
                Cancel
              </Button>
            </div>
          </form>
        )}

        {/* Key list */}
        {error && (
          <p className="text-sm text-red-500">{error}</p>
        )}

        {!loading && keys.length === 0 && !error && (
          <div className="flex flex-col items-center gap-3 py-8 text-muted-foreground">
            <Key className="size-8 opacity-30" />
            <p className="text-sm">No SSH keys stored yet.</p>
          </div>
        )}

        {keys.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Fingerprint</TableHead>
                <TableHead>Added</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {keys.map((k) => (
                <TableRow key={k.name}>
                  <TableCell className="font-medium">{k.name}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    {k.fingerprint}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {formatDate(k.created_at)}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      onClick={() => handleDelete(k.name)}
                      aria-label={`Delete key ${k.name}`}
                      className="text-muted-foreground hover:text-red-500"
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
