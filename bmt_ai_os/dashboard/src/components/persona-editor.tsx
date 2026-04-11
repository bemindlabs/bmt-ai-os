"use client";

import { useState, useEffect, useCallback } from "react";
import {
  getPersona,
  savePersona,
  listPresets,
  applyPreset,
  type PresetInfo,
} from "@/lib/api";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const MAX_CHARS = 32_000;

const PRESET_DESCRIPTIONS: Record<string, string> = {
  coding:
    "Precise engineering assistant. Favours accuracy, code examples, and edge-case awareness.",
  general:
    "Friendly, knowledgeable assistant. Balanced, conversational, and approachable.",
  creative:
    "Expressive writing partner. Vivid language, narrative structure, and collaborative tone.",
};

export function PersonaEditor() {
  const [content, setContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [presets, setPresets] = useState<PresetInfo[]>([]);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [applyingPreset, setApplyingPreset] = useState<string | null>(null);

  const loadPersona = useCallback(async () => {
    try {
      const data = await getPersona();
      setContent(data.content);
      setSavedContent(data.content);
      setWorkspace(data.workspace);
    } catch {
      setError("Failed to load persona. Is the controller running?");
    }
  }, []);

  const loadPresets = useCallback(async () => {
    try {
      const data = await listPresets();
      setPresets(data.presets);
    } catch {
      // Non-fatal — presets list is optional
    }
  }, []);

  useEffect(() => {
    loadPersona();
    loadPresets();
  }, [loadPersona, loadPresets]);

  async function handleSave() {
    setSaving(true);
    setStatus(null);
    setError(null);
    try {
      const data = await savePersona(content);
      setSavedContent(data.content);
      setWorkspace(data.workspace);
      setStatus("Persona saved.");
    } catch {
      setError("Failed to save persona.");
    } finally {
      setSaving(false);
    }
  }

  async function handleApplyPreset(name: string) {
    setApplyingPreset(name);
    setStatus(null);
    setError(null);
    try {
      await applyPreset(name);
      // Reload the active persona so editor and preview reflect the new content
      const data = await getPersona();
      setContent(data.content);
      setSavedContent(data.content);
      setWorkspace(data.workspace);
      setStatus(`Preset '${name}' applied.`);
    } catch {
      setError(`Failed to apply preset '${name}'.`);
    } finally {
      setApplyingPreset(null);
    }
  }

  const isDirty = content !== savedContent;

  return (
    <div className="space-y-4">
      {/* Status / error banner */}
      {status && (
        <p className="text-sm text-green-600 dark:text-green-400">{status}</p>
      )}
      {error && (
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      )}

      <Tabs defaultValue="editor">
        <TabsList>
          <TabsTrigger value="editor">Editor</TabsTrigger>
          <TabsTrigger value="presets">Presets</TabsTrigger>
          <TabsTrigger value="preview">Live Preview</TabsTrigger>
        </TabsList>

        {/* ------------------------------------------------------------------ */}
        {/* Editor tab                                                          */}
        {/* ------------------------------------------------------------------ */}
        <TabsContent value="editor">
          <div className="mt-4 space-y-3">
            {workspace && (
              <p className="text-xs text-muted-foreground">
                Workspace:{" "}
                <code className="font-mono bg-muted px-1.5 py-0.5 rounded text-xs">
                  {workspace}/SOUL.md
                </code>
              </p>
            )}
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              maxLength={MAX_CHARS}
              rows={18}
              spellCheck={false}
              className="w-full resize-y rounded-md border border-input bg-background px-3 py-2 font-mono text-sm text-foreground shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              placeholder="Enter SOUL.md content — this defines your agent's persona and behaviour."
            />
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">
                {content.length.toLocaleString()} / {MAX_CHARS.toLocaleString()} characters
              </span>
              <Button
                onClick={handleSave}
                disabled={saving || !isDirty}
                size="sm"
              >
                {saving ? "Saving…" : isDirty ? "Save Changes" : "Saved"}
              </Button>
            </div>
          </div>
        </TabsContent>

        {/* ------------------------------------------------------------------ */}
        {/* Presets tab                                                         */}
        {/* ------------------------------------------------------------------ */}
        <TabsContent value="presets">
          <div className="mt-4 grid gap-4 sm:grid-cols-3">
            {presets.length === 0 ? (
              <p className="col-span-3 text-sm text-muted-foreground">
                No presets available.
              </p>
            ) : (
              presets.map((preset) => (
                <Card key={preset.name} className="flex flex-col">
                  <CardHeader className="pb-2">
                    <CardTitle className="capitalize text-base">
                      {preset.name}
                    </CardTitle>
                    <CardDescription className="text-xs">
                      {PRESET_DESCRIPTIONS[preset.name] ?? ""}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="flex flex-1 flex-col justify-between gap-3">
                    <pre className="overflow-auto rounded bg-muted px-2 py-2 text-[11px] leading-relaxed max-h-36 whitespace-pre-wrap">
                      {preset.content.slice(0, 300)}
                      {preset.content.length > 300 ? "…" : ""}
                    </pre>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleApplyPreset(preset.name)}
                      disabled={applyingPreset === preset.name}
                      className="w-full"
                    >
                      {applyingPreset === preset.name ? "Applying…" : "Apply"}
                    </Button>
                  </CardContent>
                </Card>
              ))
            )}
          </div>
        </TabsContent>

        {/* ------------------------------------------------------------------ */}
        {/* Live Preview tab                                                    */}
        {/* ------------------------------------------------------------------ */}
        <TabsContent value="preview">
          <div className="mt-4 space-y-3">
            <p className="text-xs text-muted-foreground">
              Read-only view of the assembled system prompt that will be sent to
              the model. This reflects the current editor content (unsaved
              changes are included).
            </p>
            <div className="rounded-md border border-dashed border-border bg-muted/40 p-4">
              {content.trim() ? (
                <pre className="whitespace-pre-wrap font-mono text-sm leading-relaxed text-foreground">
                  {content}
                </pre>
              ) : (
                <p className="text-sm text-muted-foreground italic">
                  No persona content. Edit the SOUL.md above or apply a preset.
                </p>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              {content.length.toLocaleString()} characters
              {isDirty ? " (unsaved)" : ""}
            </p>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
