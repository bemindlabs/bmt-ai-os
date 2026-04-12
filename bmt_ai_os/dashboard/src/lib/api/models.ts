import { apiFetch } from "./client";

export interface OllamaModel {
  name: string;
  size: number;
  modified_at: string;
  digest?: string;
}

export interface ModelsResponse {
  models: OllamaModel[];
}

export async function fetchModels(): Promise<ModelsResponse> {
  return apiFetch<ModelsResponse>("/api/models");
}

export async function fetchProviderModels(
  _name: string,
): Promise<{ models: { id: string; name?: string }[] }> {
  const res = await apiFetch<{ object: string; data: { id: string; name?: string }[] }>(
    `/v1/models`,
  );
  return { models: res.data ?? [] };
}
