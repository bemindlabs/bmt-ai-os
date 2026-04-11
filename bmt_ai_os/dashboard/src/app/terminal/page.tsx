import { Suspense } from "react";
import { TerminalLoader } from "./terminal-loader";

export default function TerminalPage() {
  return (
    <div className="flex h-full flex-col space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Terminal</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Browser-based shell access — local or remote via SSH.
        </p>
      </div>

      {/* Fill the remaining vertical space with the terminal */}
      <div className="flex min-h-0 flex-1 overflow-hidden rounded-lg border border-border">
        {/*
          Suspense is required here because TerminalView uses useSearchParams
          which opts into client-side rendering. The fallback prevents the
          build from failing due to missing Suspense boundary.
        */}
        <Suspense
          fallback={
            <div className="flex h-full w-full items-center justify-center rounded-lg bg-zinc-950">
              <span className="animate-pulse font-mono text-sm text-zinc-500">
                Loading terminal...
              </span>
            </div>
          }
        >
          <TerminalLoader />
        </Suspense>
      </div>
    </div>
  );
}
