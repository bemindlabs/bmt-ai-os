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
  discovered?: boolean;
  latency_ms?: number;
  latency_history?: number[];
  error_count?: number;
  cooldown_remaining_s?: number;
  last_success_ts?: number | null;
  [key: string]: unknown;
}

export interface DiscoveredProvider {
  name: string;
  port: number;
  base_url: string;
  provider_type: string;
  latency_ms: number;
  already_registered: boolean;
  registered_now: boolean;
  discovered: true;
  error: string | null;
  discovered_at: number;
}

export interface DiscoverResponse {
  discovered: DiscoveredProvider[];
  count: number;
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
    providers: raw.providers.map((p) => {
      const health = p.health as Record<string, unknown> | undefined;
      return {
        ...p,
        name: p.name as string,
        healthy:
          typeof p.healthy === "boolean"
            ? p.healthy
            : !!(health?.healthy),
        active: p.active as boolean | undefined,
        discovered: p.discovered as boolean | undefined,
        latency_ms: (health?.latency_ms as number | undefined) ?? (p.latency_ms as number | undefined),
        latency_history: p.latency_history as number[] | undefined,
        error_count: p.error_count as number | undefined,
        cooldown_remaining_s: p.cooldown_remaining_s as number | undefined,
        last_success_ts: p.last_success_ts as number | null | undefined,
      };
    }),
  };
}

export async function discoverProviders(): Promise<DiscoverResponse> {
  return apiFetch<DiscoverResponse>("/api/v1/providers/discover");
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
// Provider Key Management (BMTOS-134)
// ---------------------------------------------------------------------------

export interface ProviderKey {
  id: string;
  provider_name: string;
  masked_key: string;
  usage_count: number;
  last_used: number | null;
  last_error: string | null;
  cooldown_until: number | null;
  status: "active" | "cooldown";
}

export interface ProviderKeysResponse {
  provider_name: string;
  keys: ProviderKey[];
  total: number;
}

export interface AddKeyResponse {
  provider_name: string;
  key: ProviderKey;
}

export async function fetchProviderKeys(
  providerName: string,
): Promise<ProviderKeysResponse> {
  return apiFetch<ProviderKeysResponse>(
    `/api/v1/providers/config/${encodeURIComponent(providerName)}/keys`,
  );
}

export async function addProviderKey(
  providerName: string,
  apiKey: string,
): Promise<AddKeyResponse> {
  return apiFetch<AddKeyResponse>(
    `/api/v1/providers/config/${encodeURIComponent(providerName)}/keys`,
    {
      method: "POST",
      body: JSON.stringify({ api_key: apiKey }),
    },
  );
}

export async function deleteProviderKey(
  providerName: string,
  keyId: string,
): Promise<{ deleted: boolean; key_id: string; provider_name: string }> {
  return apiFetch(
    `/api/v1/providers/config/${encodeURIComponent(providerName)}/keys/${encodeURIComponent(keyId)}`,
    { method: "DELETE" },
  );
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
// Fleet (BMTOS-128)
// ---------------------------------------------------------------------------

export interface FleetDevice {
  device_id: string;
  hostname: string;
  arch: string;
  board: string;
  os_version: string;
  online: boolean;
  cpu_percent: number;
  memory_percent: number;
  disk_percent: number;
  loaded_models: string[];
  registered_at?: string;
  last_seen?: string;
  [key: string]: unknown;
}

export interface FleetDevicesResponse {
  devices: FleetDevice[];
  total: number;
  online: number;
}

export async function fetchFleetDevices(): Promise<FleetDevicesResponse> {
  return apiFetch<FleetDevicesResponse>("/api/v1/fleet/devices");
}

export async function deployModel(req: { model: string; device_ids: string[] }): Promise<{ status: string; targeted_devices: string[]; device_count: number }> {
  return apiFetch("/api/v1/fleet/deploy-model", { method: "POST", body: JSON.stringify(req) });
}

// ---------------------------------------------------------------------------
// SSH Key Management (BMTOS-129)
// ---------------------------------------------------------------------------

export interface SshKeySummary {
  name: string;
  fingerprint: string;
  created_at: string;
}

export async function fetchSshKeys(): Promise<SshKeySummary[]> {
  return apiFetch<SshKeySummary[]>("/api/v1/ssh-keys");
}

export async function uploadSshKey(name: string, key: string): Promise<SshKeySummary> {
  return apiFetch<SshKeySummary>("/api/v1/ssh-keys", {
    method: "POST",
    body: JSON.stringify({ name, key }),
  });
}

export async function deleteSshKey(name: string): Promise<{ deleted: boolean; name: string }> {
  return apiFetch<{ deleted: boolean; name: string }>(`/api/v1/ssh-keys/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
}

// ---------------------------------------------------------------------------
// Knowledge / RAG
// ---------------------------------------------------------------------------
export interface RagCollection { name: string; count: number; }
export async function fetchCollections(): Promise<RagCollection[]> {
  const res = await apiFetch<RagCollection[] | { collections: RagCollection[] }>("/api/v1/collections");
  return Array.isArray(res) ? res : res.collections;
}
export async function ingestDocuments(req: { path: string; collection?: string; recursive?: boolean }): Promise<{ status: string; path: string; collection: string }> { return apiFetch("/api/v1/ingest", { method: "POST", body: JSON.stringify(req) }); }
export async function searchKnowledge(req: { question: string; collection?: string; top_k?: number }): Promise<RagQueryResponse> { return apiFetch("/api/v1/query", { method: "POST", body: JSON.stringify(req) }); }
export async function deleteCollection(name: string): Promise<{ status: string }> { return apiFetch(`/api/v1/collections/${name}`, { method: "DELETE" }); }

// ---------------------------------------------------------------------------
// Workspace
// ---------------------------------------------------------------------------
export async function fetchWorkspace(): Promise<{ workspace: string }> {
  return apiFetch("/api/v1/settings/workspace");
}

// ---------------------------------------------------------------------------
// Files
// ---------------------------------------------------------------------------
export type Breadcrumb = { name: string; path: string };
export interface FileEntry { name: string; path: string; is_dir: boolean; size: number; modified: string; }
export async function listFiles(path: string): Promise<{ entries: FileEntry[]; breadcrumbs: { name: string; path: string }[] }> { return apiFetch(`/api/v1/files/list?path=${encodeURIComponent(path)}`); }
export async function readFile(path: string): Promise<{ content: string; path: string }> { return apiFetch(`/api/v1/files/read?path=${encodeURIComponent(path)}`); }
export function downloadFileUrl(path: string): string { return `/api/v1/files/download?path=${encodeURIComponent(path)}`; }
export async function writeFile(path: string, content: string): Promise<{ status: string; path: string; size: number }> {
  return apiFetch("/api/v1/files/write", { method: "PUT", body: JSON.stringify({ path, content }) });
}
export async function uploadFile(path: string, file: File): Promise<{ status: string }> { const form = new FormData(); form.append("file", file); const res = await fetch(`/api/v1/files/upload?path=${encodeURIComponent(path)}`, { method: "POST", body: form }); if (!res.ok) throw new Error(`${res.status}`); return res.json(); }
export async function createDirectory(path: string): Promise<{ status: string }> {
  return apiFetch("/api/v1/files/mkdir", { method: "POST", body: JSON.stringify({ path }) });
}
export async function renameFile(oldPath: string, newPath: string): Promise<{ status: string }> {
  return apiFetch("/api/v1/files/rename", { method: "POST", body: JSON.stringify({ old_path: oldPath, new_path: newPath }) });
}
export async function deleteFile(path: string): Promise<{ status: string }> {
  return apiFetch(`/api/v1/files/delete?path=${encodeURIComponent(path)}`, { method: "DELETE" });
}
export async function ingestPath(path: string): Promise<{ status: string }> { return apiFetch("/api/v1/ingest", { method: "POST", body: JSON.stringify({ path }) }); }

// ---------------------------------------------------------------------------
// Training
// ---------------------------------------------------------------------------
export interface TrainingJob {
  id: string;
  model: string;
  dataset: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  progress: number;
  created_at: string;
  updated_at: string;
  config?: Record<string, unknown>;
  current_loss?: number | null;
  tokens_per_sec?: number | null;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  current_epoch?: number | null;
  epochs?: number | null;
  current_step?: number | null;
  total_steps?: number | null;
  learning_rate?: number | null;
  dataset_rows?: number | null;
  dataset_preview?: unknown[][] | null;
  dataset_headers?: string[] | null;
}

export interface TrainingJobListResponse {
  jobs: TrainingJob[];
  total: number;
  page: number;
  page_size: number;
}

export interface TrainingMetricPoint {
  step: number;
  loss: number;
  learning_rate?: number;
  epoch?: number;
  tokens_per_sec?: number;
}

export interface TrainingMetricsResponse {
  metrics: TrainingMetricPoint[];
}

export async function fetchTrainingJobs(page = 1, pageSize = 20): Promise<TrainingJobListResponse> {
  return apiFetch(`/api/v1/training/jobs?page=${page}&page_size=${pageSize}`);
}

export async function fetchTrainingJob(id: string): Promise<TrainingJob> {
  return apiFetch(`/api/v1/training/jobs/${id}`);
}

export async function createTrainingJob(req: { model: string; dataset: string; config?: Record<string, unknown> }): Promise<TrainingJob> {
  return apiFetch("/api/v1/training/jobs", { method: "POST", body: JSON.stringify(req) });
}

export async function cancelTrainingJob(id: string): Promise<{ status: string }> {
  return apiFetch(`/api/v1/training/jobs/${id}/cancel`, { method: "POST" });
}

export async function fetchTrainingMetrics(id: string): Promise<TrainingMetricsResponse> {
  return apiFetch(`/api/v1/training/jobs/${id}/metrics`);
}

// ---------------------------------------------------------------------------
// Agents / Persona
// ---------------------------------------------------------------------------
export interface AgentPreset { name: string; description: string; content?: string; }
export async function fetchAgents(): Promise<{ presets: AgentPreset[] }> { try { return await apiFetch("/api/v1/persona/presets"); } catch { return { presets: [{ name: "default", description: "General AI assistant" }, { name: "coding", description: "Coding assistant" }, { name: "creative", description: "Creative writer" }] }; } }

export async function activatePersona(
  name: string,
): Promise<{ active: string; workspace_path: string }> {
  return apiFetch(`/api/v1/persona/activate/${encodeURIComponent(name)}`, {
    method: "POST",
  });
}

export async function fetchActivePersona(): Promise<{
  active: string | null;
  workspace_path: string | null;
}> {
  return apiFetch("/api/v1/persona/active");
}

// ---------------------------------------------------------------------------
// Fallback Chain + Provider Models
// ---------------------------------------------------------------------------
export async function setFallbackOrder(order: string[]): Promise<{ order: string[] }> {
  return apiFetch("/api/v1/providers/fallback-order", { method: "PUT", body: JSON.stringify({ order }) });
}
export async function fetchProviderModels(name: string): Promise<{ models: { id: string; name?: string }[] }> {
  const res = await apiFetch<{ object: string; data: { id: string; name?: string }[] }>(`/v1/models`);
  return { models: res.data ?? [] };
}
