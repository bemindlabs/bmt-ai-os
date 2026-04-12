"use client";

import { Input } from "@/components/ui/input";

// ---------------------------------------------------------------------------
// AiOptionsPanel
// ---------------------------------------------------------------------------

interface AiOptionsPanelProps {
  temperature: number;
  maxTokens: number;
  onTemperatureChange: (value: number) => void;
  onMaxTokensChange: (value: number) => void;
}

export function AiOptionsPanel({
  temperature,
  maxTokens,
  onTemperatureChange,
  onMaxTokensChange,
}: AiOptionsPanelProps) {
  return (
    <div className="space-y-2 rounded border border-border bg-muted/20 p-2">
      <div className="flex items-center justify-between gap-2">
        <label className="text-[10px] text-muted-foreground">
          Temperature
        </label>
        <div className="flex items-center gap-1.5">
          <input
            type="range"
            min={0}
            max={2}
            step={0.1}
            value={temperature}
            onChange={(e) => onTemperatureChange(parseFloat(e.target.value))}
            className="w-20 h-1 accent-primary"
          />
          <span className="text-xs font-mono w-7 text-right text-foreground">
            {temperature.toFixed(1)}
          </span>
        </div>
      </div>
      <div className="flex items-center justify-between gap-2">
        <label className="text-[10px] text-muted-foreground">
          Max tokens
        </label>
        <Input
          type="number"
          min={256}
          max={32768}
          step={256}
          value={maxTokens}
          onChange={(e) => onMaxTokensChange(parseInt(e.target.value, 10) || 4096)}
          className="h-6 w-20 text-xs font-mono text-right"
        />
      </div>
      <p className="text-[10px] text-muted-foreground">
        Low temperature (0.1-0.3) for precise code. Higher (0.7+) for creative suggestions.
      </p>
    </div>
  );
}
