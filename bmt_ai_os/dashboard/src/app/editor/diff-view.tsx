"use client";

import { useMemo } from "react";
import { Button } from "@/components/ui/button";
import { computeDiff, diffStats } from "@/lib/diff";
import { Check, X } from "lucide-react";

export interface DiffViewProps {
  /** Original file content (current state in editor) */
  original: string;
  /** Modified content produced by the AI */
  modified: string;
  /** Language identifier shown in the header (e.g. "typescript") */
  language: string;
  /** File name / path shown in the header */
  fileName?: string;
  /** Called when the user accepts the changes */
  onApply: () => void;
  /** Called when the user rejects the changes */
  onReject: () => void;
}

/**
 * Renders a unified diff between `original` and `modified` with:
 * - Green background + "+" marker for added lines
 * - Red background + "-" marker for removed lines
 * - Neutral background for unchanged lines
 * - Dual line-number gutter (old | new)
 * - Summary header: "X added, Y removed"
 * - "Apply Changes" and "Reject" action buttons
 */
export function DiffView({
  original,
  modified,
  language,
  fileName,
  onApply,
  onReject,
}: DiffViewProps) {
  const lines = useMemo(() => computeDiff(original, modified), [original, modified]);
  const stats = useMemo(() => diffStats(lines), [lines]);

  const hasChanges = stats.added > 0 || stats.removed > 0;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-border bg-muted/30 px-3 py-2 gap-3">
        <div className="flex items-center gap-2 min-w-0">
          {fileName && (
            <span className="truncate font-mono text-xs text-foreground">
              {fileName}
            </span>
          )}
          {fileName && <span className="text-muted-foreground text-xs">·</span>}
          {hasChanges ? (
            <span className="text-xs text-muted-foreground whitespace-nowrap">
              {stats.added > 0 && (
                <span className="text-green-500 font-medium">
                  +{stats.added}
                </span>
              )}
              {stats.added > 0 && stats.removed > 0 && (
                <span className="text-muted-foreground mx-1">/</span>
              )}
              {stats.removed > 0 && (
                <span className="text-red-500 font-medium">
                  -{stats.removed}
                </span>
              )}
              <span className="ml-1">
                {stats.added > 0 && stats.removed > 0
                  ? "lines changed"
                  : stats.added > 0
                    ? stats.added === 1
                      ? "line added"
                      : "lines added"
                    : stats.removed === 1
                      ? "line removed"
                      : "lines removed"}
              </span>
            </span>
          ) : (
            <span className="text-xs text-muted-foreground">No changes</span>
          )}
          {language && (
            <>
              <span className="text-muted-foreground text-xs">·</span>
              <span className="text-[10px] text-muted-foreground uppercase tracking-wide">
                {language}
              </span>
            </>
          )}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <Button
            size="sm"
            onClick={onApply}
            disabled={!hasChanges}
            className="h-7 gap-1.5 text-xs bg-green-600 hover:bg-green-500 text-white border-transparent"
          >
            <Check className="size-3" />
            Apply Changes
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={onReject}
            className="h-7 gap-1.5 text-xs"
          >
            <X className="size-3" />
            Reject
          </Button>
        </div>
      </div>

      {/* Diff body */}
      <div className="flex-1 overflow-auto">
        <table className="w-full border-collapse font-mono text-xs leading-5">
          <colgroup>
            {/* old line no */}
            <col className="w-10 shrink-0" />
            {/* new line no */}
            <col className="w-10 shrink-0" />
            {/* marker */}
            <col className="w-5 shrink-0" />
            {/* content */}
            <col />
          </colgroup>
          <tbody>
            {lines.map((line, idx) => {
              const isAdd = line.type === "add";
              const isRemove = line.type === "remove";

              const rowBg = isAdd
                ? "bg-green-950/40 dark:bg-green-950/60"
                : isRemove
                  ? "bg-red-950/40 dark:bg-red-950/60"
                  : "";

              const gutterBg = isAdd
                ? "bg-green-950/60 dark:bg-green-950/80"
                : isRemove
                  ? "bg-red-950/60 dark:bg-red-950/80"
                  : "bg-muted/20";

              const markerColor = isAdd
                ? "text-green-400 select-none"
                : isRemove
                  ? "text-red-400 select-none"
                  : "text-transparent select-none";

              const contentColor = isAdd
                ? "text-green-100 dark:text-green-200"
                : isRemove
                  ? "text-red-200 dark:text-red-300 line-through decoration-red-500/50"
                  : "text-foreground";

              return (
                <tr key={idx} className={rowBg}>
                  {/* old line number */}
                  <td
                    className={`${gutterBg} px-2 text-right text-[10px] text-muted-foreground select-none border-r border-border/40 align-top`}
                  >
                    {isAdd ? "" : line.oldLineNo}
                  </td>
                  {/* new line number */}
                  <td
                    className={`${gutterBg} px-2 text-right text-[10px] text-muted-foreground select-none border-r border-border/40 align-top`}
                  >
                    {isRemove ? "" : line.newLineNo}
                  </td>
                  {/* +/- marker */}
                  <td className={`px-1 text-center font-bold ${markerColor} align-top`}>
                    {isAdd ? "+" : isRemove ? "-" : " "}
                  </td>
                  {/* line content */}
                  <td className={`pl-1 pr-4 whitespace-pre ${contentColor} align-top`}>
                    {line.content || " "}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {lines.length === 0 && (
          <div className="flex items-center justify-center p-8 text-xs text-muted-foreground">
            Both files are empty.
          </div>
        )}
      </div>
    </div>
  );
}
