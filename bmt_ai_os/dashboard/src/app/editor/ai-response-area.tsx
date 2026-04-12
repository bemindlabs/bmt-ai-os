"use client";

import { useState } from "react";
import {
  Copy,
  Check,
  Replace,
  Diff,
  FilePlus,
  Wrench,
  ChevronRight,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { ToolCallSummary } from "@/lib/api";
import { DiffView } from "./diff-view";
import { MultiFileEdit, parseMultiFileResponse } from "./multi-file-edit";
import { ModelCompare } from "./model-compare";
import { extractCode } from "./editor-prompts";

// ---------------------------------------------------------------------------
// AiResponseArea
// ---------------------------------------------------------------------------

interface AiResponseAreaProps {
  response: string;
  loading: boolean;
  toolCalls: ToolCallSummary[];
  showDiff: boolean;
  onShowDiff: (show: boolean) => void;
  compareMode: boolean;
  onCloseCompare: () => void;
  multiFileMode: boolean;
  onCloseMultiFile: () => void;
  fileContent: string;
  language: string;
  filePath: string | null;
  currentDir: string;
  temperature: number;
  maxTokens: number;
  onApply: (code: string) => void;
  onFileCreated?: () => void;
}

export function AiResponseArea({
  response,
  loading,
  toolCalls,
  showDiff,
  onShowDiff,
  compareMode,
  onCloseCompare,
  multiFileMode,
  onCloseMultiFile,
  fileContent,
  language,
  filePath,
  currentDir,
  temperature,
  maxTokens,
  onApply,
  onFileCreated,
}: AiResponseAreaProps) {
  const [copied, setCopied] = useState(false);
  const [showSaveAs, setShowSaveAs] = useState(false);
  const [saveAsPath, setSaveAsPath] = useState("");
  const [saveAsStatus, setSaveAsStatus] = useState<"idle" | "saving" | "done" | "error">("idle");
  const [expandedTools, setExpandedTools] = useState<Set<string>>(new Set());

  const handleCopy = () => {
    navigator.clipboard.writeText(response);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleApply = () => {
    onApply(extractCode(response));
    onShowDiff(false);
  };

  const handleSaveAs = async () => {
    if (!saveAsPath.trim() || !response.trim()) return;
    setSaveAsStatus("saving");
    try {
      const { writeFile } = await import("@/lib/api");
      const code = extractCode(response);
      const fullPath = saveAsPath.startsWith("/")
        ? saveAsPath
        : currentDir
          ? `${currentDir}/${saveAsPath}`
          : saveAsPath;
      await writeFile(fullPath, code);
      setSaveAsStatus("done");
      onFileCreated?.();
      setTimeout(() => {
        setSaveAsStatus("idle");
        setShowSaveAs(false);
      }, 1500);
    } catch {
      setSaveAsStatus("error");
      setTimeout(() => setSaveAsStatus("idle"), 2000);
    }
  };

  const toggleToolExpand = (key: string) => {
    setExpandedTools((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  // ---------------------------------------------------------------------------
  // Mode: compare
  // ---------------------------------------------------------------------------

  if (compareMode) {
    return (
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <ModelCompare
          prompt=""
          fileContent={fileContent}
          filePath={filePath}
          language={language}
          temperature={temperature}
          maxTokens={maxTokens}
          onApply={onApply}
          onClose={onCloseCompare}
        />
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Mode: multi-file
  // ---------------------------------------------------------------------------

  if (multiFileMode && response && parseMultiFileResponse(response).length > 0) {
    return (
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <MultiFileEdit
          response={response}
          currentDir={currentDir}
          onApplyFile={(_path, _content) => {
            onFileCreated?.();
          }}
          onApplyAll={() => {
            onFileCreated?.();
          }}
          onClose={onCloseMultiFile}
        />
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Mode: diff preview
  // ---------------------------------------------------------------------------

  if (showDiff && response) {
    return (
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <DiffView
          original={fileContent}
          modified={extractCode(response)}
          language={language}
          fileName={filePath ? filePath.split("/").pop() : undefined}
          onApply={handleApply}
          onReject={() => onShowDiff(false)}
        />
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Mode: normal response / empty state
  // ---------------------------------------------------------------------------

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {response ? (
        <>
          <div className="flex-1 overflow-auto p-3 space-y-2">
            {/* Tool call log */}
            {toolCalls.length > 0 && (
              <div className="space-y-1">
                {toolCalls.map((tc) => {
                  const key = tc.id;
                  const expanded = expandedTools.has(key);
                  return (
                    <div
                      key={key}
                      className="rounded border border-border bg-muted/20 text-[10px]"
                    >
                      <button
                        type="button"
                        onClick={() => toggleToolExpand(key)}
                        className="flex w-full items-center gap-1.5 px-2 py-1 text-left hover:bg-muted/40"
                      >
                        <Wrench className="size-2.5 text-orange-400 shrink-0" />
                        <span className="font-mono text-orange-400">{tc.name}</span>
                        <span className="text-muted-foreground truncate">
                          ({Object.entries(tc.arguments)
                            .map(([k, v]) => `${k}="${String(v)}"`)
                            .join(", ")})
                        </span>
                        <ChevronRight
                          className={[
                            "ml-auto size-2.5 text-muted-foreground shrink-0 transition-transform",
                            expanded ? "rotate-90" : "",
                          ].join(" ")}
                        />
                      </button>
                      {expanded && (
                        <pre className="border-t border-border px-2 py-1 whitespace-pre-wrap font-mono text-[10px] text-muted-foreground max-h-32 overflow-auto">
                          {tc.result_preview}
                        </pre>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
            <pre className="whitespace-pre-wrap font-mono text-xs text-foreground">
              {response}
            </pre>
          </div>

          <div className="shrink-0 border-t border-border px-3 py-2 space-y-2">
            <div className="flex items-center gap-2">
              {/* Preview Diff — only when a file is open */}
              {fileContent.trim() && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onShowDiff(true)}
                  disabled={loading}
                  className="h-7 gap-1.5 text-xs"
                  title="Preview changes before applying"
                >
                  <Diff className="size-3" />
                  Preview Diff
                </Button>
              )}
              {/* Apply directly (skip diff review) */}
              <Button
                size="sm"
                onClick={handleApply}
                disabled={loading}
                className="h-7 gap-1.5 text-xs"
                title="Apply to editor without reviewing diff"
              >
                <Replace className="size-3" />
                Apply
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setShowSaveAs(!showSaveAs);
                  setSaveAsPath(
                    currentDir
                      ? `${currentDir}/new-file.${language === "plaintext" ? "txt" : language}`
                      : "",
                  );
                }}
                className="h-7 gap-1.5 text-xs"
              >
                <FilePlus className="size-3" />
                Save As
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={handleCopy}
                className="h-7 gap-1.5 text-xs"
              >
                {copied ? (
                  <Check className="size-3" />
                ) : (
                  <Copy className="size-3" />
                )}
              </Button>
            </div>

            {/* Save As file path input */}
            {showSaveAs && (
              <div className="flex items-center gap-1.5">
                <Input
                  value={saveAsPath}
                  onChange={(e) => setSaveAsPath(e.target.value)}
                  placeholder="path/to/new-file.py"
                  className="flex-1 h-7 text-xs font-mono"
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void handleSaveAs();
                    if (e.key === "Escape") setShowSaveAs(false);
                  }}
                  autoFocus
                />
                <Button
                  size="sm"
                  onClick={() => void handleSaveAs()}
                  disabled={!saveAsPath.trim() || saveAsStatus === "saving"}
                  className="h-7 text-xs shrink-0"
                >
                  {saveAsStatus === "saving"
                    ? "Saving..."
                    : saveAsStatus === "done"
                      ? "Created!"
                      : saveAsStatus === "error"
                        ? "Failed"
                        : "Create"}
                </Button>
              </div>
            )}
          </div>
        </>
      ) : (
        <div className="flex flex-1 items-center justify-center p-4">
          <p className="text-center text-xs text-muted-foreground whitespace-pre-line">
            {loading
              ? "Generating code..."
              : "Describe what you want to code.\nThe AI will use the current file as context."}
          </p>
        </div>
      )}
    </div>
  );
}
