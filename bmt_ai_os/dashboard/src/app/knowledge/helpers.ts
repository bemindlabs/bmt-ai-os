/**
 * Returns the persona-scoped collection name.
 * When no persona is active the empty string is treated as "default" by callers.
 */
export function personaCollection(activePersona: string | null): string {
  return activePersona ? `persona_${activePersona}` : "";
}

/**
 * Returns the persona-scoped workspace files path.
 * Falls back to the server-provided workspace_path when available.
 */
export function personaFilesPath(
  activePersona: string | null,
  workspacePath: string | null,
): string {
  if (!activePersona) return "";
  if (workspacePath) return workspacePath;
  return `workspace/agents/${activePersona}/files`;
}
