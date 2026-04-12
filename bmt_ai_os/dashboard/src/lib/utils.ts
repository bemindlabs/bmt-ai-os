import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Format an ISO date string for display. Returns "—" for null/undefined. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

/** Strip the provider prefix from a model ID for display. */
export function displayModelName(modelId: string): string {
  return modelId.includes("/") ? modelId.split("/").slice(1).join("/") : modelId;
}

/**
 * Build a provider-qualified model identifier for the chat API.
 * e.g. resolveModel("openai", "gpt-4") → "openai/gpt-4"
 */
export function resolveModel(provider: string, model: string): string {
  if (provider === "default") return model;
  if (!model || model === "default") return provider;
  if (!model.toLowerCase().startsWith(provider.toLowerCase() + "/")) {
    return `${provider}/${model}`;
  }
  return model;
}
