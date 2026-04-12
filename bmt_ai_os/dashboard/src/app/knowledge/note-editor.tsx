"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import { MarkdownPreview } from "@/components/markdown-preview";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { Save, Link, Tag, ChevronDown, ChevronUp } from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface NoteEditorProps {
  filePath: string | null;
  content: string;
  backlinks: string[];
  onSave: (content: string) => Promise<void>;
  onNavigate: (target: string) => void;
}

// ---------------------------------------------------------------------------
// Frontmatter parsing
// ---------------------------------------------------------------------------

interface Frontmatter {
  title?: string;
  tags?: string[];
  [key: string]: unknown;
}

function parseFrontmatter(raw: string): {
  frontmatter: Frontmatter | null;
  body: string;
} {
  const match = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/);
  if (!match) return { frontmatter: null, body: raw };

  const yamlBlock = match[1];
  const body = match[2];

  // Minimal YAML parser — handles simple key: value and key: [a, b] lists
  const fm: Frontmatter = {};
  for (const line of yamlBlock.split("\n")) {
    const colonIdx = line.indexOf(":");
    if (colonIdx === -1) continue;
    const key = line.slice(0, colonIdx).trim();
    const value = line.slice(colonIdx + 1).trim();
    if (!key) continue;

    // Array literal: [a, b, c]
    if (value.startsWith("[") && value.endsWith("]")) {
      fm[key] = value
        .slice(1, -1)
        .split(",")
        .map((v) => v.trim())
        .filter(Boolean);
    } else {
      fm[key] = value;
    }
  }

  return { frontmatter: fm, body };
}

function serializeFrontmatter(fm: Frontmatter, body: string): string {
  const lines: string[] = ["---"];
  for (const [k, v] of Object.entries(fm)) {
    if (Array.isArray(v)) {
      lines.push(`${k}: [${v.join(", ")}]`);
    } else if (v !== undefined && v !== "") {
      lines.push(`${k}: ${v}`);
    }
  }
  lines.push("---");
  lines.push("");
  lines.push(body);
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Wiki-link & tag rendering helpers
// ---------------------------------------------------------------------------

/**
 * Replace [[Target]] with <a> tags and #tag with badge spans in raw markdown
 * before passing to react-markdown, so that the standard renderer sees clean
 * HTML.  We work on the plain text source and replace inline patterns.
 */
function preprocessMarkdown(
  text: string,
  onNavigate: (target: string) => void,
): React.ReactNode[] {
  const parts = text.split(/(\[\[[^\]]+\]\]|#[\w/]+)/g);
  return parts.map((part, idx) => {
    // Wiki link
    const wikiMatch = part.match(/^\[\[(.+)\]\]$/);
    if (wikiMatch) {
      const target = wikiMatch[1];
      return (
        <button
          key={idx}
          className="inline cursor-pointer rounded px-0.5 text-blue-500 underline-offset-2 hover:underline focus:outline-none"
          onClick={() => onNavigate(target)}
          type="button"
          aria-label={`Open note: ${target}`}
        >
          {target}
        </button>
      );
    }

    // Hashtag — avoid false positives on headings at line start
    const tagMatch = part.match(/^#([\w/]+)$/);
    if (tagMatch) {
      return (
        <Badge key={idx} variant="secondary" className="mx-0.5 align-text-top text-xs">
          {tagMatch[1]}
        </Badge>
      );
    }

    return <span key={idx}>{part}</span>;
  });
}

// Custom paragraph component that processes wiki-links and tags inline
function NotePreviewContent({
  rawBody,
  onNavigate,
}: {
  rawBody: string;
  onNavigate: (target: string) => void;
}) {
  // Override the paragraph renderer to inject wiki-link/tag interactivity.
  // MarkdownPreview handles GFM tables, code highlighting, headings, etc.
  const wikiComponents = {
    p({ children }: React.ComponentProps<"p">) {
      const text = extractText(children);
      return <p className="mb-3 leading-relaxed">{preprocessMarkdown(text, onNavigate)}</p>;
    },
  };

  return (
    <MarkdownPreview components={wikiComponents as Record<string, React.ComponentType<unknown>>}>
      {rawBody}
    </MarkdownPreview>
  );
}

/** Recursively extract plain text from React children (for re-processing). */
function extractText(children: React.ReactNode): string {
  if (typeof children === "string") return children;
  if (typeof children === "number") return String(children);
  if (Array.isArray(children)) return children.map(extractText).join("");
  if (children && typeof children === "object" && "props" in children) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return extractText((children as any).props.children);
  }
  return "";
}

// ---------------------------------------------------------------------------
// Frontmatter editor strip
// ---------------------------------------------------------------------------

function FrontmatterEditor({
  frontmatter,
  onChange,
}: {
  frontmatter: Frontmatter;
  onChange: (updated: Frontmatter) => void;
}) {
  const [tagInput, setTagInput] = useState("");
  const tags: string[] = Array.isArray(frontmatter.tags)
    ? (frontmatter.tags as string[])
    : [];

  function addTag() {
    const t = tagInput.trim().replace(/^#/, "");
    if (!t || tags.includes(t)) {
      setTagInput("");
      return;
    }
    onChange({ ...frontmatter, tags: [...tags, t] });
    setTagInput("");
  }

  function removeTag(tag: string) {
    onChange({ ...frontmatter, tags: tags.filter((t) => t !== tag) });
  }

  return (
    <div className="space-y-3 rounded-lg border border-border bg-muted/30 p-3">
      <div className="flex items-center gap-2">
        <label className="w-14 shrink-0 text-xs font-medium text-muted-foreground">
          Title
        </label>
        <Input
          value={(frontmatter.title as string) ?? ""}
          onChange={(e) => onChange({ ...frontmatter, title: e.target.value })}
          placeholder="Note title"
          className="h-7 text-sm"
        />
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <label className="w-14 shrink-0 text-xs font-medium text-muted-foreground">
          Tags
        </label>
        {tags.map((tag) => (
          <Badge
            key={tag}
            variant="secondary"
            className="cursor-pointer gap-1 text-xs"
            onClick={() => removeTag(tag)}
            title="Click to remove"
          >
            <Tag className="size-2.5" />
            {tag}
          </Badge>
        ))}
        <div className="flex items-center gap-1">
          <Input
            value={tagInput}
            onChange={(e) => setTagInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === ",") {
                e.preventDefault();
                addTag();
              }
            }}
            placeholder="Add tag..."
            className="h-6 w-24 px-1.5 text-xs"
          />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Backlinks panel
// ---------------------------------------------------------------------------

function BacklinksPanel({
  backlinks,
  onNavigate,
}: {
  backlinks: string[];
  onNavigate: (target: string) => void;
}) {
  const [expanded, setExpanded] = useState(true);
  if (backlinks.length === 0) return null;

  return (
    <div className="mt-4 rounded-lg border border-border">
      <button
        className="flex w-full items-center justify-between px-3 py-2 text-xs font-medium text-muted-foreground hover:bg-muted/50"
        onClick={() => setExpanded((v) => !v)}
        type="button"
      >
        <span className="flex items-center gap-1.5">
          <Link className="size-3" />
          Backlinks ({backlinks.length})
        </span>
        {expanded ? <ChevronUp className="size-3" /> : <ChevronDown className="size-3" />}
      </button>
      {expanded && (
        <ul className="divide-y divide-border">
          {backlinks.map((bl) => (
            <li key={bl}>
              <button
                className="w-full px-3 py-1.5 text-left text-xs text-blue-500 hover:bg-muted/50 hover:underline"
                onClick={() => onNavigate(bl)}
                type="button"
              >
                {bl}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main NoteEditor component
// ---------------------------------------------------------------------------

export function NoteEditor({
  filePath,
  content,
  backlinks,
  onSave,
  onNavigate,
}: NoteEditorProps) {
  const [rawContent, setRawContent] = useState(content);
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saved" | "error">("idle");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Sync external content changes (e.g. when a different file is opened)
  useEffect(() => {
    setRawContent(content);
    setSaveStatus("idle");
  }, [content, filePath]);

  // Ctrl+S / Cmd+S to save
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        void triggerSave();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rawContent]);

  const triggerSave = useCallback(async () => {
    if (!filePath) return;
    setSaving(true);
    try {
      await onSave(rawContent);
      setSaveStatus("saved");
      setTimeout(() => setSaveStatus("idle"), 2000);
    } catch {
      setSaveStatus("error");
    } finally {
      setSaving(false);
    }
  }, [filePath, rawContent, onSave]);

  // Parse frontmatter
  const { frontmatter, body } = parseFrontmatter(rawContent);

  function handleFrontmatterChange(updated: Frontmatter) {
    const next = serializeFrontmatter(updated, body);
    setRawContent(next);
  }

  if (!filePath) {
    return (
      <div className="flex h-full flex-col items-center justify-center text-muted-foreground">
        <p className="text-sm">Select a note or create a new one.</p>
      </div>
    );
  }

  const noteName = filePath.split("/").pop()?.replace(/\.md$/, "") ?? filePath;

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between">
        <span className="truncate text-sm font-medium text-foreground">{noteName}</span>
        <div className="flex items-center gap-2">
          {saveStatus === "saved" && (
            <span className="text-xs text-green-500">Saved</span>
          )}
          {saveStatus === "error" && (
            <span className="text-xs text-destructive">Save failed</span>
          )}
          <Button
            size="sm"
            variant="outline"
            onClick={triggerSave}
            disabled={saving || !filePath}
            aria-label="Save note (Ctrl+S)"
          >
            <Save className="size-3.5" />
            <span className="ml-1">{saving ? "Saving..." : "Save"}</span>
          </Button>
        </div>
      </div>

      {/* Frontmatter editor */}
      {frontmatter && (
        <div className="shrink-0">
          <FrontmatterEditor
            frontmatter={frontmatter}
            onChange={handleFrontmatterChange}
          />
        </div>
      )}

      {/* Split editor / preview */}
      <div className="flex min-h-0 flex-1 gap-3">
        {/* Left: source editor */}
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="mb-1 text-xs font-medium text-muted-foreground">Source</div>
          <textarea
            ref={textareaRef}
            value={rawContent}
            onChange={(e) => {
              setRawContent(e.target.value);
              setSaveStatus("idle");
            }}
            spellCheck={false}
            className={cn(
              "flex-1 resize-none rounded-lg border border-border bg-background p-3",
              "font-mono text-sm leading-relaxed text-foreground outline-none",
              "focus:ring-2 focus:ring-ring/50",
              "min-h-0",
            )}
            aria-label="Note markdown source"
            placeholder={"# Note title\n\nStart writing...\n\nUse [[Note Name]] for wiki-links and #tag for tags."}
          />
        </div>

        {/* Right: preview */}
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="mb-1 text-xs font-medium text-muted-foreground">Preview</div>
          <Card className="flex-1 overflow-y-auto p-0">
            <CardContent className="p-3 text-sm">
              <NotePreviewContent rawBody={body} onNavigate={onNavigate} />
              <BacklinksPanel backlinks={backlinks} onNavigate={onNavigate} />
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// New note template helper (exported for use in NoteList)
// ---------------------------------------------------------------------------

export function newNoteTemplate(title: string): string {
  const date = new Date().toISOString().split("T")[0];
  return `---\ntitle: ${title}\ntags: []\ncreated: ${date}\n---\n\n# ${title}\n\n`;
}
