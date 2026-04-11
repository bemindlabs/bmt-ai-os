import { LogViewer } from "./log-viewer";

export default function LogsPage() {
  return (
    <div className="flex h-full flex-col space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Logs</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Recent controller API request logs. Auto-refreshes every 5 seconds.
        </p>
      </div>
      <LogViewer />
    </div>
  );
}
