const BASE_URL =
  typeof window === "undefined"
    ? (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080")
    : "";

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

export interface OllamaModel {
  name: string;
  size: number;
  modified_at: string;
  digest?: string;
}

export interface ModelsResponse {
  models: OllamaModel[];
}

export interface Provider {
  name: string;
  healthy: boolean;
  active?: boolean;
  [key: string]: unknown;
}

export interface ProvidersResponse {
  providers: Provider[];
  active?: string;
}

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

export interface ChatRequest {
  model: string;
  messages: ChatMessage[];
  stream?: boolean;
}

export interface ChatResponse {
  id: string;
  object: string;
  created: number;
  model: string;
  choices: {
    index: number;
    message: ChatMessage;
    finish_reason: string;
  }[];
}

function getAuthHeader(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const token = localStorage.getItem("bmt_auth_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...getAuthHeader(),
      ...(init?.headers ?? {}),
    },
    // Do not cache — data should be fresh
    cache: "no-store",
  });

  if (res.status === 401 && typeof window !== "undefined") {
    // Clear stale credentials and redirect to login
    localStorage.removeItem("bmt_auth_token");
    localStorage.removeItem("bmt_auth_user");
    window.location.replace("/login");
    throw new Error("Session expired");
  }

  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${res.statusText}`);
  }

  return res.json() as Promise<T>;
}

export async function fetchStatus(): Promise<StatusResponse> {
  return apiFetch<StatusResponse>("/api/v1/status");
}

export async function fetchMetrics(): Promise<MetricsResponse> {
  return apiFetch<MetricsResponse>("/api/v1/metrics");
}

export async function fetchModels(): Promise<ModelsResponse> {
  return apiFetch<ModelsResponse>("/api/models");
}

export async function fetchProviders(): Promise<ProvidersResponse> {
  const raw = await apiFetch<{ providers: Record<string, unknown>[]; active?: string }>(
    "/api/v1/providers",
  );
  return {
    ...raw,
    providers: raw.providers.map((p) => ({
      ...p,
      name: p.name as string,
      healthy:
        typeof p.healthy === "boolean"
          ? p.healthy
          : !!(p.health as Record<string, unknown> | undefined)?.healthy,
      active: p.active as boolean | undefined,
    })),
  };
}

export async function setActiveProvider(name: string): Promise<unknown> {
  return apiFetch<unknown>("/api/v1/providers/active", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export async function sendChat(req: ChatRequest): Promise<ChatResponse> {
  return apiFetch<ChatResponse>("/v1/chat/completions", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

export function formatUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const parts: string[] = [];
  if (d > 0) parts.push(`${d}d`);
  if (h > 0) parts.push(`${h}h`);
  parts.push(`${m}m`);
  return parts.join(" ");
}

// ---------------------------------------------------------------------------
// SSE Streaming Chat (BMTOS-76)
// ---------------------------------------------------------------------------

export async function streamChat(
  req: ChatRequest,
  signal?: AbortSignal,
): Promise<ReadableStreamDefaultReader<string>> {
  const res = await fetch(`${BASE_URL}/v1/chat/completions`, {
    method: "POST",
    headers: { ...getAuthHeader(), "Content-Type": "application/json" },
    body: JSON.stringify({ ...req, stream: true }),
    signal,
  });

  if (!res.ok) throw new Error(`${res.status}: ${res.statusText}`);
  if (!res.body) throw new Error("Response body is null");

  return res.body.pipeThrough(new TextDecoderStream()).getReader();
}

// ---------------------------------------------------------------------------
// RAG Query (BMTOS-80)
// ---------------------------------------------------------------------------

export interface RagSource {
  filename: string;
  chunk: string;
  score: number;
  position?: number;
}

export interface RagQueryRequest {
  question: string;
  collection?: string;
  top_k?: number;
}

export interface RagQueryResponse {
  answer: string;
  sources: RagSource[];
  latency_ms: number;
}

export async function queryRag(
  req: RagQueryRequest,
): Promise<RagQueryResponse> {
  return apiFetch<RagQueryResponse>("/api/v1/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
}

// ---------------------------------------------------------------------------
// File Manager (BMTOS-116)
// ---------------------------------------------------------------------------

export interface FileEntry {
  name: string;
  path: string;
  is_dir: boolean;
  size: number | null;
  modified: number;
  mime: string | null;
}

export interface Breadcrumb {
  name: string;
  path: string;
}

export interface ListFilesResponse {
  entries: FileEntry[];
  breadcrumbs: Breadcrumb[];
}

export interface ReadFileResponse {
  path: string;
  name: string;
  content: string;
  size: number;
  mime: string;
}

export interface UploadFileResponse {
  status: string;
  path: string;
  name: string;
  size: number;
}

export async function listFiles(path = ""): Promise<ListFilesResponse> {
  const qs = path ? `?path=${encodeURIComponent(path)}` : "";
  return apiFetch<ListFilesResponse>(`/api/v1/files/list${qs}`);
}

export async function readFile(path: string): Promise<ReadFileResponse> {
  return apiFetch<ReadFileResponse>(
    `/api/v1/files/read?path=${encodeURIComponent(path)}`,
  );
}

export function downloadFileUrl(path: string): string {
  const token =
    typeof window !== "undefined"
      ? (localStorage.getItem("bmt_auth_token") ?? "")
      : "";
  return `/api/v1/files/download?path=${encodeURIComponent(path)}&token=${encodeURIComponent(token)}`;
}

export async function uploadFile(
  dirPath: string,
  file: File,
): Promise<UploadFileResponse> {
  const token =
    typeof window !== "undefined"
      ? (localStorage.getItem("bmt_auth_token") ?? "")
      : "";
  const formData = new FormData();
  formData.append("file", file);
  const qs = dirPath ? `?path=${encodeURIComponent(dirPath)}` : "";
  const res = await fetch(`/api/v1/files/upload${qs}`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: formData,
  });
  if (res.status === 401 && typeof window !== "undefined") {
    localStorage.removeItem("bmt_auth_token");
    localStorage.removeItem("bmt_auth_user");
    window.location.replace("/login");
    throw new Error("Session expired");
  }
  if (!res.ok) throw new Error(`Upload failed: ${res.statusText}`);
  return res.json() as Promise<UploadFileResponse>;
}

export async function ingestPath(
  path: string,
  collection = "default",
): Promise<unknown> {
  return apiFetch<unknown>("/api/v1/ingest", {
    method: "POST",
    body: JSON.stringify({ path: `/${path}`, collection, recursive: true }),
  });
}
