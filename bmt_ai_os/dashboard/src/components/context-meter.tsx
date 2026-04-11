"use client";

import { cn } from "@/lib/utils";

export const TOKEN_BUDGET = 128_000;

/** Approximate token count: 1 token ≈ 4 characters */
export function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

interface ContextMeterProps {
  usedTokens: number;
  budgetTokens?: number;
  className?: string;
}

function getColorClass(pct: number): string {
  if (pct >= 85) return "bg-destructive";
  if (pct >= 70) return "bg-amber-500";
  return "bg-emerald-500";
}

function getTextColorClass(pct: number): string {
  if (pct >= 85) return "text-destructive";
  if (pct >= 70) return "text-amber-500";
  return "text-emerald-600 dark:text-emerald-400";
}

function formatTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

export function ContextMeter({
  usedTokens,
  budgetTokens = TOKEN_BUDGET,
  className,
}: ContextMeterProps) {
  const pct = Math.min(100, Math.round((usedTokens / budgetTokens) * 100));
  const colorFill = getColorClass(pct);
  const colorText = getTextColorClass(pct);

  return (
    <div
      className={cn("flex items-center gap-2", className)}
      title={`${usedTokens.toLocaleString()} / ${budgetTokens.toLocaleString()} tokens used`}
      aria-label={`Context usage: ${pct}% (${usedTokens.toLocaleString()} of ${budgetTokens.toLocaleString()} tokens)`}
    >
      <span className="text-xs text-muted-foreground shrink-0">Context</span>

      {/* Track */}
      <div
        className="relative h-2 flex-1 overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        {/* Fill */}
        <div
          className={cn(
            "h-full rounded-full transition-[width] duration-300",
            colorFill
          )}
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* Label */}
      <span className={cn("text-xs font-medium tabular-nums shrink-0", colorText)}>
        {formatTokens(usedTokens)}&thinsp;/&thinsp;{formatTokens(budgetTokens)}
      </span>
    </div>
  );
}
