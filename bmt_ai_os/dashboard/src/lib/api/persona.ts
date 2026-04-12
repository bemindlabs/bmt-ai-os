import { apiFetch } from "./client";

export interface AgentPreset {
  name: string;
  description: string;
  content?: string;
}

export async function fetchAgents(): Promise<{ presets: AgentPreset[] }> {
  try {
    return await apiFetch("/api/v1/persona/presets");
  } catch {
    return {
      presets: [
        { name: "default", description: "General AI assistant" },
        { name: "coding", description: "Coding assistant" },
        { name: "creative", description: "Creative writer" },
      ],
    };
  }
}

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
