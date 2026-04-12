"use client";

import { useEffect, useRef } from "react";
import {
  Bug,
  Wrench,
  BookOpen,
  FlaskConical,
  FileText,
  Zap,
  Shield,
  Code2,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Data
// ---------------------------------------------------------------------------

export interface EditorSlashCommand {
  name: string;
  label: string;
  description: string;
  Icon: React.ComponentType<{ className?: string }>;
  systemPrompt: string;
}

export const EDITOR_SLASH_COMMANDS: EditorSlashCommand[] = [
  {
    name: "fix",
    label: "Fix Bugs",
    description: "Find and fix bugs in the current code",
    Icon: Bug,
    systemPrompt:
      "You are a bug-fixing assistant. Analyze the code carefully, identify bugs, and return the fixed code. Explain each bug you found briefly as a comment.",
  },
  {
    name: "refactor",
    label: "Refactor",
    description: "Improve code structure and readability",
    Icon: Wrench,
    systemPrompt:
      "You are a refactoring assistant. Improve the code structure, naming, and readability without changing behavior. Apply clean code principles.",
  },
  {
    name: "explain",
    label: "Explain Code",
    description: "Explain how the current code works",
    Icon: BookOpen,
    systemPrompt:
      "You are a code explainer. Explain the code in detail — what it does, how it works, and any notable patterns or potential issues. Use clear, concise language.",
  },
  {
    name: "test",
    label: "Generate Tests",
    description: "Write unit tests for the current code",
    Icon: FlaskConical,
    systemPrompt:
      "You are a test-writing assistant. Generate comprehensive unit tests for the provided code. Use the appropriate test framework for the language. Cover edge cases.",
  },
  {
    name: "doc",
    label: "Add Documentation",
    description: "Add docstrings and comments",
    Icon: FileText,
    systemPrompt:
      "You are a documentation assistant. Add clear docstrings, type annotations, and inline comments to the code. Follow the language's documentation conventions.",
  },
  {
    name: "optimize",
    label: "Optimize",
    description: "Improve performance and efficiency",
    Icon: Zap,
    systemPrompt:
      "You are a performance optimization assistant. Analyze the code for performance issues and return an optimized version. Explain what you improved.",
  },
  {
    name: "security",
    label: "Security Audit",
    description: "Check for security vulnerabilities",
    Icon: Shield,
    systemPrompt:
      "You are a security auditor. Analyze the code for security vulnerabilities (injection, XSS, auth issues, etc). Return the fixed code with security comments.",
  },
];

// ---------------------------------------------------------------------------
// Filtering
// ---------------------------------------------------------------------------

export function filterEditorCommands(query: string): EditorSlashCommand[] {
  const lower = query.toLowerCase();
  if (!lower) return EDITOR_SLASH_COMMANDS;
  return EDITOR_SLASH_COMMANDS.filter(
    (cmd) =>
      cmd.name.includes(lower) ||
      cmd.label.toLowerCase().includes(lower),
  );
}

// ---------------------------------------------------------------------------
// Popup component
// ---------------------------------------------------------------------------

interface SlashCommandPopupProps {
  query: string;
  activeIndex: number;
  onSelect: (cmd: EditorSlashCommand) => void;
  onActiveIndexChange: (index: number) => void;
}

export function SlashCommandPopup({
  query,
  activeIndex,
  onSelect,
  onActiveIndexChange,
}: SlashCommandPopupProps) {
  const listRef = useRef<HTMLUListElement>(null);
  const commands = filterEditorCommands(query);

  // Scroll highlighted item into view on keyboard navigation.
  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const item = list.children[activeIndex] as HTMLElement | undefined;
    item?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  if (commands.length === 0) return null;

  return (
    <div
      role="listbox"
      aria-label="Slash commands"
      className="absolute bottom-full left-0 z-50 mb-1 w-72 overflow-hidden rounded-lg border border-border bg-popover shadow-md"
    >
      <div className="flex items-center gap-1.5 border-b border-border px-3 py-1.5">
        <Code2 className="size-3 text-muted-foreground" />
        <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">
          Commands
        </span>
      </div>
      <ul ref={listRef} className="max-h-56 overflow-y-auto py-1">
        {commands.map((cmd, i) => (
          <li
            key={cmd.name}
            role="option"
            aria-selected={i === activeIndex}
            className={cn(
              "flex cursor-pointer items-start gap-2.5 px-3 py-2 transition-colors",
              i === activeIndex
                ? "bg-accent text-accent-foreground"
                : "text-foreground hover:bg-muted",
            )}
            onMouseEnter={() => onActiveIndexChange(i)}
            onMouseDown={(e) => {
              // Prevent textarea blur before the click fires.
              e.preventDefault();
              onSelect(cmd);
            }}
          >
            <cmd.Icon
              className={cn(
                "mt-0.5 size-3.5 shrink-0",
                i === activeIndex ? "text-accent-foreground" : "text-primary",
              )}
            />
            <div className="min-w-0">
              <span className="block text-xs font-semibold leading-tight">
                {cmd.label}
                <span className="ml-1.5 font-mono font-normal text-muted-foreground">
                  /{cmd.name}
                </span>
              </span>
              <span className="block text-[10px] leading-tight text-muted-foreground mt-0.5">
                {cmd.description}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
