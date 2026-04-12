import { apiFetch } from "./client";

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

export interface RagCollection {
  name: string;
  count: number;
}

export async function queryRag(req: RagQueryRequest): Promise<RagQueryResponse> {
  return apiFetch<RagQueryResponse>("/api/v1/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
}

export async function fetchCollections(): Promise<RagCollection[]> {
  const res = await apiFetch<RagCollection[] | { collections: RagCollection[] }>(
    "/api/v1/collections",
  );
  return Array.isArray(res) ? res : res.collections;
}

export async function ingestDocuments(req: {
  path: string;
  collection?: string;
  recursive?: boolean;
}): Promise<{ status: string; path: string; collection: string }> {
  return apiFetch("/api/v1/ingest", { method: "POST", body: JSON.stringify(req) });
}

export async function searchKnowledge(req: {
  question: string;
  collection?: string;
  top_k?: number;
}): Promise<RagQueryResponse> {
  return apiFetch("/api/v1/query", { method: "POST", body: JSON.stringify(req) });
}

export async function deleteCollection(name: string): Promise<{ status: string }> {
  return apiFetch(`/api/v1/collections/${name}`, { method: "DELETE" });
}
