import { TerminalLoader } from "./terminal-loader";

export default function TerminalPage() {
  return (
    <div className="flex h-full flex-col space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Terminal</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Browser-based shell access to the BMT AI OS controller host.
        </p>
      </div>

      {/* Fill the remaining vertical space with the terminal */}
      <div className="flex min-h-0 flex-1 overflow-hidden rounded-lg border border-border">
        <TerminalLoader />
      </div>
    </div>
  );
}
