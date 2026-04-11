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

export async function setFallbackOrder(order: string[]): Promise<{ order: string[] }> {
  return apiFetch<{ order: string[] }>("/api/v1/providers/fallback-order", {
    method: "PUT",
    body: JSON.stringify({ order }),
  });
}

export async function fetchProviderModels(name: string): Promise<{ models: { id: string; name?: string; [key: string]: unknown }[] }> {
  return apiFetch<{ models: { id: string; name?: string; [key: string]: unknown }[] }>(
    `/api/v1/providers/${encodeURIComponent(name)}/models`,
  );
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
// Provider CRUD (BMTOS-120)
// ---------------------------------------------------------------------------

export type ProviderType =
  | "ollama"
  | "openai"
  | "anthropic"
  | "gemini"
  | "groq"
  | "mistral"
  | "vllm"
  | "llamacpp";

export interface ProviderConfig {
  name: string;
  provider_type: ProviderType;
  base_url: string;
  api_key: string; // masked on reads
  default_model: string;
  enabled: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface ProviderConfigsResponse {
  providers: ProviderConfig[];
}

export interface ProviderConfigIn {
  name: string;
  provider_type: ProviderType;
  base_url?: string;
  api_key?: string;
  default_model?: string;
  enabled?: boolean;
}

export interface ProviderConfigUpdate {
  base_url?: string;
  api_key?: string;
  default_model?: string;
  enabled?: boolean;
}

export interface ProviderTestResult {
  name: string;
  healthy: boolean;
  latency_ms: number;
  error: string | null;
}

export const PROVIDER_DEFAULT_URLS: Record<ProviderType, string> = {
  ollama: "http://localhost:11434",
  openai: "https://api.openai.com/v1",
  anthropic: "https://api.anthropic.com",
  gemini: "https://generativelanguage.googleapis.com",
  groq: "https://api.groq.com/openai/v1",
  mistral: "https://api.mistral.ai/v1",
  vllm: "http://localhost:8000/v1",
  llamacpp: "http://localhost:8080",
};

export async function fetchProviderConfigs(): Promise<ProviderConfigsResponse> {
  return apiFetch<ProviderConfigsResponse>("/api/v1/providers/config");
}

export async function createProviderConfig(
  data: ProviderConfigIn,
): Promise<ProviderConfig> {
  return apiFetch<ProviderConfig>("/api/v1/providers/config", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function updateProviderConfig(
  name: string,
  data: ProviderConfigUpdate,
): Promise<ProviderConfig> {
  return apiFetch<ProviderConfig>(`/api/v1/providers/config/${encodeURIComponent(name)}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function deleteProviderConfig(name: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/api/v1/providers/config/${encodeURIComponent(name)}`, {
    method: "DELETE",
    headers: { ...getAuthHeader() },
    cache: "no-store",
  });
  if (res.status === 401 && typeof window !== "undefined") {
    localStorage.removeItem("bmt_auth_token");
    localStorage.removeItem("bmt_auth_user");
    window.location.replace("/login");
    throw new Error("Session expired");
  }
  if (!res.ok && res.status !== 204) {
    throw new Error(`API error ${res.status}: ${res.statusText}`);
  }
}

export async function testProviderConnection(
  name: string,
): Promise<ProviderTestResult> {
  return apiFetch<ProviderTestResult>(
    `/api/v1/providers/config/${encodeURIComponent(name)}/test`,
    { method: "POST" },
  );
}
