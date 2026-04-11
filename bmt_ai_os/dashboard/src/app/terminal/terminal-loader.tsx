"use client";

// This Client Component is the required boundary for next/dynamic with ssr:false
// in Next.js 16. The dynamic import is allowed here because this file itself is
// a Client Component (the "use client" directive is present).
import dynamic from "next/dynamic";

const TerminalView = dynamic(
  () => import("./terminal-view").then((m) => m.TerminalView),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full w-full items-center justify-center rounded-lg bg-zinc-950">
        <span className="animate-pulse font-mono text-sm text-zinc-500">
          Loading terminal...
        </span>
      </div>
    ),
  }
);

export function TerminalLoader() {
  return <TerminalView />;
}
