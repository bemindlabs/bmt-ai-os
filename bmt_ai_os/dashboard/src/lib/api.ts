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
// Persona API (BMTOS-106)
// ---------------------------------------------------------------------------

export interface PersonaResponse {
  content: string;
  workspace: string;
}

export interface PresetInfo {
  name: string;
  content: string;
}

export interface PresetsResponse {
  presets: PresetInfo[];
}

export interface ApplyPresetResponse {
  name: string;
  workspace: string;
  message: string;
}

export async function getPersona(): Promise<PersonaResponse> {
  return apiFetch<PersonaResponse>("/api/v1/persona");
}

export async function savePersona(content: string): Promise<PersonaResponse> {
  return apiFetch<PersonaResponse>("/api/v1/persona", {
    method: "PUT",
    body: JSON.stringify({ content }),
  });
}

export async function listPresets(): Promise<PresetsResponse> {
  return apiFetch<PresetsResponse>("/api/v1/persona/presets");
}

export async function applyPreset(name: string): Promise<ApplyPresetResponse> {
  return apiFetch<ApplyPresetResponse>(`/api/v1/persona/presets/${name}/apply`, {
    method: "POST",
  });
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
// Agents / Persona Presets (BMTOS-108)
// ---------------------------------------------------------------------------

export interface AgentPreset {
  id: string;
  name: string;
  summary: string;
  model: string;
  workspace: string;
}

export interface AgentsResponse {
  agents: AgentPreset[];
}

/** Fetch agent personas from the controller persona-presets API.
 *  Falls back to hardcoded defaults if the endpoint is unavailable. */
export async function fetchAgents(): Promise<AgentsResponse> {
  try {
    return await apiFetch<AgentsResponse>("/api/v1/persona/presets");
  } catch {
    // Offline fallback — use the three built-in presets
    return {
      agents: [
        {
          id: "default",
          name: "Default",
          summary:
            "You are a friendly, knowledgeable AI assistant running on BMT AI OS.",
          model: "qwen2.5:7b",
          workspace: "~/.bmt/workspaces/default",
        },
        {
          id: "coding",
          name: "Coding",
          summary:
            "You are a precise, expert software engineering assistant running on BMT AI OS.",
          model: "qwen2.5-coder:7b",
          workspace: "~/.bmt/workspaces/coding",
        },
        {
          id: "creative",
          name: "Creative",
          summary:
            "You are an expressive, imaginative creative writing assistant running on BMT AI OS.",
          model: "qwen2.5:7b",
          workspace: "~/.bmt/workspaces/creative",
        },
      ],
    };
  }
}
