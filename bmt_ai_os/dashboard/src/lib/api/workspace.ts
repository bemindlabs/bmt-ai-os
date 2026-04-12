import { apiFetch } from "./client";

export async function fetchWorkspace(): Promise<{ workspace: string }> {
  return apiFetch("/api/v1/settings/workspace");
}
