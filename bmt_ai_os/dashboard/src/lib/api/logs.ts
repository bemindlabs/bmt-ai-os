import { apiFetch } from "./client";

export interface LogEntry {
  timestamp: number;
  method: string;
  path: string;
  status: number;
  elapsed_ms: number;
  trace_id: string | null;
}

export interface LogsResponse {
  logs: LogEntry[];
}

export async function fetchLogs(): Promise<LogsResponse> {
  return apiFetch<LogsResponse>("/api/v1/logs");
}
