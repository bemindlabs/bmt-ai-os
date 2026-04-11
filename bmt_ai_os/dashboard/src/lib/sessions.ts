import type { ChatMessage } from "@/lib/api";

export interface Session {
  id: string;
  title: string;
  messages: ChatMessage[];
  model: string;
  createdAt: number;
  updatedAt: number;
}

const STORAGE_KEY = "bmt_chat_sessions";
const INDEX_KEY = "bmt_chat_session_index";

/** Generate a session ID. */
function newId(): string {
  return `session_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
}

/** Derive a title from the first user message (max 60 chars). */
export function titleFromMessages(messages: ChatMessage[]): string {
  const first = messages.find((m) => m.role === "user");
  if (!first) return "New conversation";
  const text = first.content.trim().replace(/\s+/g, " ");
  return text.length > 60 ? `${text.slice(0, 57)}…` : text;
}

/** Read the ordered list of session IDs from localStorage. */
function readIndex(): string[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(localStorage.getItem(INDEX_KEY) ?? "[]") as string[];
  } catch {
    return [];
  }
}

/** Persist the ordered list of session IDs. */
function writeIndex(ids: string[]): void {
  localStorage.setItem(INDEX_KEY, JSON.stringify(ids));
}

/** Return all sessions ordered most-recently-updated first. */
export function listSessions(): Session[] {
  if (typeof window === "undefined") return [];
  const ids = readIndex();
  const sessions: Session[] = [];
  for (const id of ids) {
    const raw = localStorage.getItem(`${STORAGE_KEY}_${id}`);
    if (!raw) continue;
    try {
      sessions.push(JSON.parse(raw) as Session);
    } catch {
      // Skip corrupted entries
    }
  }
  return sessions.sort((a, b) => b.updatedAt - a.updatedAt);
}

/** Return a single session by ID, or null if not found. */
export function getSession(id: string): Session | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(`${STORAGE_KEY}_${id}`);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Session;
  } catch {
    return null;
  }
}

/**
 * Create a new empty session and return it.
 * The caller owns the returned `id` and must pass it to `saveSession`.
 */
export function createSession(model: string): Session {
  const session: Session = {
    id: newId(),
    title: "New conversation",
    messages: [],
    model,
    createdAt: Date.now(),
    updatedAt: Date.now(),
  };
  const ids = readIndex();
  if (!ids.includes(session.id)) {
    writeIndex([session.id, ...ids]);
  }
  localStorage.setItem(`${STORAGE_KEY}_${session.id}`, JSON.stringify(session));
  return session;
}

/**
 * Persist updated messages (and optionally a model) for an existing session.
 * Title is derived from the first user message automatically.
 */
export function saveSession(
  id: string,
  messages: ChatMessage[],
  model?: string,
): void {
  if (typeof window === "undefined") return;
  const existing = getSession(id);
  const now = Date.now();
  const session: Session = {
    id,
    title: titleFromMessages(messages),
    messages,
    model: model ?? existing?.model ?? "",
    createdAt: existing?.createdAt ?? now,
    updatedAt: now,
  };
  // Ensure the ID is in the index
  const ids = readIndex();
  if (!ids.includes(id)) {
    writeIndex([id, ...ids]);
  }
  localStorage.setItem(`${STORAGE_KEY}_${id}`, JSON.stringify(session));
}

/** Remove a session entirely. */
export function deleteSession(id: string): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(`${STORAGE_KEY}_${id}`);
  writeIndex(readIndex().filter((i) => i !== id));
}
