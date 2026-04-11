export default function LogsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Logs</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          System and service logs. Streaming log output is not yet available in
          this version.
        </p>
      </div>

      <div className="rounded-xl border border-border bg-muted/30 p-6">
        <p className="text-sm text-muted-foreground">
          Log streaming endpoint not yet exposed by the controller API.
          Check container logs directly via:
        </p>
        <pre className="mt-3 rounded-lg bg-muted px-4 py-3 text-xs font-mono text-foreground overflow-x-auto">
          {`docker compose -f bmt-ai-os/ai-stack/docker-compose.yml logs -f`}
        </pre>
      </div>
    </div>
  );
}
