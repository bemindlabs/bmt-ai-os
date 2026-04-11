"use client";

import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import { type SlashCommand } from "@/lib/commands";

interface SlashCommandMenuProps {
  commands: SlashCommand[];
  activeIndex: number;
  onSelect: (command: SlashCommand) => void;
  onActiveIndexChange: (index: number) => void;
}

export function SlashCommandMenu({
  commands,
  activeIndex,
  onSelect,
  onActiveIndexChange,
}: SlashCommandMenuProps) {
  const listRef = useRef<HTMLUListElement>(null);

  // Scroll the highlighted item into view when navigating by keyboard.
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
      <ul ref={listRef} className="max-h-56 overflow-y-auto py-1">
        {commands.map((cmd, i) => (
          <li
            key={cmd.name}
            role="option"
            aria-selected={i === activeIndex}
            className={cn(
              "flex cursor-pointer flex-col gap-0.5 px-3 py-2 text-sm transition-colors",
              i === activeIndex
                ? "bg-accent text-accent-foreground"
                : "text-foreground hover:bg-muted",
            )}
            onMouseEnter={() => onActiveIndexChange(i)}
            onMouseDown={(e) => {
              // Prevent textarea blur before the click registers.
              e.preventDefault();
              onSelect(cmd);
            }}
          >
            <span className="font-mono font-semibold text-primary">
              /{cmd.name}
              {cmd.hasArg && (
                <span className="ml-1 font-normal text-muted-foreground">
                  {cmd.usage.slice(cmd.name.length + 1)}
                </span>
              )}
            </span>
            <span className="text-xs text-muted-foreground">
              {cmd.description}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
