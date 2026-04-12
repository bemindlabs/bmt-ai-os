"use client";

import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import Editor, { type OnMount } from "@monaco-editor/react";
import { Button } from "@/components/ui/button";

// ---------------------------------------------------------------------------
// Language detection from file extension
// ---------------------------------------------------------------------------

const EXT_TO_LANGUAGE: Record<string, string> = {
  ts: "typescript", tsx: "typescript", js: "javascript", jsx: "javascript",
  mjs: "javascript", cjs: "javascript", py: "python", sh: "shell",
  bash: "shell", zsh: "shell", yml: "yaml", yaml: "yaml", json: "json",
  md: "markdown", mdx: "markdown", css: "css", scss: "scss", html: "html",
  htm: "html", xml: "xml", sql: "sql", rs: "rust", go: "go", java: "java",
  kt: "kotlin", swift: "swift", c: "c", cpp: "cpp", cc: "cpp", h: "cpp",
  cs: "csharp", rb: "ruby", php: "php", toml: "ini", ini: "ini", cfg: "ini",
  conf: "ini", dockerfile: "dockerfile", makefile: "makefile", txt: "plaintext",
};

function detectLanguage(filePath: string): string {
  const name = filePath.split("/").pop() ?? "";
  const lower = name.toLowerCase();
  if (lower === "dockerfile") return "dockerfile";
  if (lower === "makefile" || lower === "gnumakefile") return "makefile";
  if (lower === ".env" || lower.startsWith(".env.")) return "shell";
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  return EXT_TO_LANGUAGE[ext] ?? "plaintext";
}

// ---------------------------------------------------------------------------
// CodeEditor component
// ---------------------------------------------------------------------------

export interface CodeEditorHandle {
  setValue: (value: string) => void;
}

interface CodeEditorProps {
  filePath: string | null;
  initialContent: string;
  onSave: (content: string) => Promise<void>;
  onContentChange?: (content: string) => void;
  saving: boolean;
}

export const CodeEditor = forwardRef<CodeEditorHandle, CodeEditorProps>(
  function CodeEditor({ filePath, initialContent, onSave, onContentChange, saving }, ref) {
    const [value, setValue] = useState(initialContent);
    const [isDirty, setIsDirty] = useState(false);
    const editorRef = useRef<Parameters<OnMount>[0] | null>(null);

    useImperativeHandle(ref, () => ({
      setValue: (v: string) => {
        setValue(v);
        setIsDirty(true);
        editorRef.current?.setValue(v);
        onContentChange?.(v);
      },
    }));

    useEffect(() => {
      setValue(initialContent);
      setIsDirty(false);
    }, [initialContent, filePath]);

    const handleMount: OnMount = (editor) => {
      editorRef.current = editor;
      editor.focus();
    };

    const handleChange = useCallback(
      (val: string | undefined) => {
        const v = val ?? "";
        setValue(v);
        setIsDirty(true);
        onContentChange?.(v);
      },
      [onContentChange],
    );

    const handleSave = useCallback(async () => {
      if (!filePath || saving) return;
      await onSave(value);
      setIsDirty(false);
    }, [filePath, saving, onSave, value]);

    useEffect(() => {
      function onKeyDown(e: KeyboardEvent) {
        if ((e.ctrlKey || e.metaKey) && e.key === "s") {
          e.preventDefault();
          void handleSave();
        }
      }
      window.addEventListener("keydown", onKeyDown);
      return () => window.removeEventListener("keydown", onKeyDown);
    }, [handleSave]);

    const language = filePath ? detectLanguage(filePath) : "plaintext";

    return (
      <div className="flex h-full flex-col">
        <div className="flex h-9 shrink-0 items-center justify-between border-b border-border bg-muted/30 px-3">
          <span className="truncate font-mono text-xs text-muted-foreground">
            {filePath ?? "No file open"}
          </span>
          <div className="flex items-center gap-2">
            {isDirty && (
              <span className="text-xs text-amber-500">unsaved</span>
            )}
            <span className="text-xs text-muted-foreground">{language}</span>
            <Button
              size="sm"
              onClick={() => void handleSave()}
              disabled={!filePath || saving || !isDirty}
              className="h-6 px-2.5 text-xs"
            >
              {saving ? "Saving..." : "Save"}
            </Button>
          </div>
        </div>

        <div className="flex-1 overflow-hidden">
          <Editor
            height="100%"
            language={language}
            value={value}
            theme="vs-dark"
            onChange={handleChange}
            onMount={handleMount}
            options={{
              fontSize: 13,
              fontFamily: '"JetBrains Mono", "Fira Code", Consolas, monospace',
              fontLigatures: true,
              lineNumbers: "on",
              minimap: { enabled: false },
              scrollBeyondLastLine: false,
              wordWrap: "on",
              tabSize: 2,
              renderWhitespace: "selection",
              bracketPairColorization: { enabled: true },
              padding: { top: 12, bottom: 12 },
              smoothScrolling: true,
            }}
            loading={
              <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                Loading editor...
              </div>
            }
          />
        </div>
      </div>
    );
  },
);
