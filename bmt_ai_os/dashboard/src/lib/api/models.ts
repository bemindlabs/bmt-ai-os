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

/**
 * Group a flat list of model IDs by provider name.
 * Models prefixed with "providerName/" are assigned to that provider;
 * providers with no prefixed models get the full list as fallback.
 */
export function groupModelsByProvider(
  modelList: { id: string; name?: string }[],
  providers: { name: string }[],
): Record<string, string[]> {
  const allIds = modelList
    .map((m) => m.id ?? m.name ?? "")
    .filter(Boolean);

  const byProvider: Record<string, string[]> = {};
  for (const p of providers) {
    const prefixed = allIds.filter((id) =>
      id.toLowerCase().startsWith(p.name.toLowerCase() + "/"),
    );
    byProvider[p.name] = prefixed.length > 0 ? prefixed : allIds;
  }
  return byProvider;
}
