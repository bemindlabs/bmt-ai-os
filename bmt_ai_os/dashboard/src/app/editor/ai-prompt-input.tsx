"use client";

import { useRef, useState, type KeyboardEvent } from "react";
import { X } from "lucide-react";
import {
  SlashCommandPopup,
  filterEditorCommands,
  type EditorSlashCommand,
} from "./slash-commands";

// ---------------------------------------------------------------------------
// AiPromptInput
// ---------------------------------------------------------------------------

interface AiPromptInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  activeCommand: EditorSlashCommand | null;
  onCommandSelect: (cmd: EditorSlashCommand) => void;
  onCommandClear: () => void;
  promptHistory: string[];
  disabled: boolean;
  placeholder: string;
}

export function AiPromptInput({
  value,
  onChange,
  onSubmit,
  activeCommand,
  onCommandSelect,
  onCommandClear,
  promptHistory,
  disabled,
  placeholder,
}: AiPromptInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [showCommands, setShowCommands] = useState(false);
  const [commandQuery, setCommandQuery] = useState("");
  const [commandIndex, setCommandIndex] = useState(0);

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const v = e.target.value;
    onChange(v);

    // Detect a "/" at the start of a line or the whole input.
    const slashMatch = v.match(/(^|\n)\/([\w]*)$/);
    if (slashMatch) {
      const q = slashMatch[2];
      setCommandQuery(q);
      setCommandIndex(0);
      setShowCommands(true);
    } else {
      setShowCommands(false);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (showCommands) {
      const filtered = filterEditorCommands(commandQuery);
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setCommandIndex((i) => (i + 1) % Math.max(filtered.length, 1));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setCommandIndex((i) =>
          (i - 1 + Math.max(filtered.length, 1)) % Math.max(filtered.length, 1),
        );
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        const cmd = filtered[commandIndex];
        if (cmd) {
          onCommandSelect(cmd);
          setShowCommands(false);
        }
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setShowCommands(false);
        return;
      }
    }
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      onSubmit();
    }
  };

  const handleCommandSelect = (cmd: EditorSlashCommand) => {
    onCommandSelect(cmd);
    setShowCommands(false);
    setTimeout(() => textareaRef.current?.focus(), 0);
  };

  return (
    <div>
      {/* Active command badge */}
      {activeCommand && (
        <div className="mb-1.5 flex items-center gap-1.5">
          <span className="inline-flex items-center gap-1 rounded bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
            <activeCommand.Icon className="size-3" />
            {activeCommand.label}
          </span>
          <button
            type="button"
            onClick={onCommandClear}
            className="text-[10px] text-muted-foreground hover:text-foreground"
            aria-label="Clear active command"
          >
            <X className="size-3" />
          </button>
        </div>
      )}

      <div className="relative">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onBlur={() => {
            // Delay so mouseDown on popup items fires first.
            setTimeout(() => setShowCommands(false), 150);
          }}
          placeholder={placeholder}
          className="w-full resize-none rounded border border-input bg-background px-3 py-2 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
          rows={3}
          spellCheck={false}
          disabled={disabled}
        />
        {showCommands && (
          <SlashCommandPopup
            query={commandQuery}
            activeIndex={commandIndex}
            onSelect={handleCommandSelect}
            onActiveIndexChange={setCommandIndex}
          />
        )}
      </div>

      {/* Prompt history */}
      {promptHistory.length > 0 && (
        <div className="mt-1.5">
          <select
            onChange={(e) => {
              if (e.target.value) onChange(e.target.value);
              e.target.value = "";
            }}
            className="w-full h-6 rounded border border-input bg-background px-1.5 text-[10px] text-muted-foreground focus:outline-none"
            defaultValue=""
          >
            <option value="" disabled>
              Prompt history ({promptHistory.length})...
            </option>
            {promptHistory.map((p, i) => (
              <option key={i} value={p}>
                {p.length > 60 ? p.slice(0, 60) + "..." : p}
              </option>
            ))}
          </select>
        </div>
      )}
    </div>
  );
}
