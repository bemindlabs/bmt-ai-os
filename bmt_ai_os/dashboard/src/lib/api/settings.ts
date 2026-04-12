import { apiFetch } from "./client";

export interface ServiceStatus {
  name: string;
  health: string;
  state?: string;
  uptime_seconds?: number | null;
  restarts?: number;
  circuit_breaker?: string;
  last_check_ms?: number | null;
  last_error?: string | null;
  [key: string]: unknown;
}

export interface StatusResponse {
  uptime_seconds: number | null;
  services: ServiceStatus[];
  version?: string;
  status?: string;
}

export interface MetricsResponse {
  total_requests: number | null;
  avg_latency_ms: number | null;
  error_rate: number | null;
  [key: string]: unknown;
}

export async function fetchStatus(): Promise<StatusResponse> {
  return apiFetch<StatusResponse>("/api/v1/status");
}

export async function fetchMetrics(): Promise<MetricsResponse> {
  return apiFetch<MetricsResponse>("/api/v1/metrics");
}
