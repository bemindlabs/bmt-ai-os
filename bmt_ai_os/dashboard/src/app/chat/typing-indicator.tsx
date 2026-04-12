"use client";

import { Bot } from "lucide-react";

export function TypingIndicator() {
  return (
    <div className="flex gap-2.5">
      <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <Bot className="size-3.5" aria-hidden="true" />
      </div>
      <div className="rounded-xl bg-muted px-3.5 py-3 text-sm">
        <span className="flex items-center gap-1" aria-label="Thinking">
          <span className="size-1.5 rounded-full bg-current animate-bounce [animation-delay:0ms]" />
          <span className="size-1.5 rounded-full bg-current animate-bounce [animation-delay:150ms]" />
          <span className="size-1.5 rounded-full bg-current animate-bounce [animation-delay:300ms]" />
        </span>
      </div>
    </div>
  );
}
