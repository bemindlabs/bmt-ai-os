"use client";

import { useCallback, useEffect, useRef, useState } from "react";

// ---------------------------------------------------------------------------
// Editor session state — persisted to localStorage
// ---------------------------------------------------------------------------

const STORAGE_KEY = "bmt_editor_session";

export interface EditorSession {
  /** Current directory path in the file tree */
  dirPath: string;
  /** Currently open file path */
  openFilePath: string | null;
  /** List of recently opened file paths (most recent first, max 20) */
  recentFiles: string[];
  /** Whether the AI panel is visible */
  showAi: boolean;
  /** Whether the terminal panel is visible */
  showTerminal: boolean;
  /** AI prompt history (last 50) */
  promptHistory: string[];
  /** Scroll position of file tree */
  fileTreeScroll: number;
  /** Last saved timestamp */
  savedAt: number;
}

const DEFAULT_SESSION: EditorSession = {
  dirPath: "",
  openFilePath: null,
  recentFiles: [],
  showAi: false,
  showTerminal: false,
  promptHistory: [],
  fileTreeScroll: 0,
  savedAt: 0,
};

function loadSession(): EditorSession {
  if (typeof window === "undefined") return DEFAULT_SESSION;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_SESSION;
    const parsed = JSON.parse(raw) as Partial<EditorSession>;
    return { ...DEFAULT_SESSION, ...parsed };
  } catch {
    return DEFAULT_SESSION;
  }
}

function saveSession(session: EditorSession): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ ...session, savedAt: Date.now() }),
    );
  } catch {
    // localStorage full or unavailable
  }
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export interface UseEditorSessionReturn {
  session: EditorSession;
  /** Update one or more session fields and persist */
  update: (patch: Partial<EditorSession>) => void;
  /** Add a file to the recent files list */
  addRecentFile: (filePath: string) => void;
  /** Add a prompt to the history */
  addPromptHistory: (prompt: string) => void;
  /** Clear session (reset to defaults) */
  clear: () => void;
}

export function useEditorSession(): UseEditorSessionReturn {
  const [session, setSession] = useState<EditorSession>(DEFAULT_SESSION);
  const initialized = useRef(false);

  // Load from localStorage on mount (client-side only)
  useEffect(() => {
    if (!initialized.current) {
      initialized.current = true;
      setSession(loadSession());
    }
  }, []);

  // Debounced save — persist 300ms after last change
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sessionRef = useRef(session);
  sessionRef.current = session;

  useEffect(() => {
    if (!initialized.current) return;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      saveSession(sessionRef.current);
    }, 300);
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, [session]);

  const update = useCallback((patch: Partial<EditorSession>) => {
    setSession((prev) => ({ ...prev, ...patch }));
  }, []);

  const addRecentFile = useCallback((filePath: string) => {
    setSession((prev) => {
      const filtered = prev.recentFiles.filter((f) => f !== filePath);
      const recentFiles = [filePath, ...filtered].slice(0, 20);
      return { ...prev, recentFiles };
    });
  }, []);

  const addPromptHistory = useCallback((prompt: string) => {
    setSession((prev) => {
      const trimmed = prompt.trim();
      if (!trimmed) return prev;
      const filtered = prev.promptHistory.filter((p) => p !== trimmed);
      const promptHistory = [trimmed, ...filtered].slice(0, 50);
      return { ...prev, promptHistory };
    });
  }, []);

  const clear = useCallback(() => {
    setSession(DEFAULT_SESSION);
    localStorage.removeItem(STORAGE_KEY);
  }, []);

  return { session, update, addRecentFile, addPromptHistory, clear };
}
