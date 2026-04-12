"use client";

import { useEffect, useState } from "react";
import { fetchWorkspace } from "@/lib/api";

const STORAGE_KEY = "bmt_workspace_dir";

/**
 * Returns the workspace directory path.
 * Checks localStorage first, then falls back to the backend API.
 * Caches the result in localStorage for subsequent loads.
 */
export function useWorkspace(): { workspace: string; loading: boolean; setWorkspace: (path: string) => void } {
  const [workspace, setWorkspaceState] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      setWorkspaceState(stored);
      setLoading(false);
      return;
    }

    fetchWorkspace()
      .then((res) => {
        setWorkspaceState(res.workspace);
        localStorage.setItem(STORAGE_KEY, res.workspace);
      })
      .catch(() => {
        // Fallback if API is unreachable
        setWorkspaceState("");
      })
      .finally(() => setLoading(false));
  }, []);

  function setWorkspace(path: string) {
    setWorkspaceState(path);
    localStorage.setItem(STORAGE_KEY, path);
  }

  return { workspace, loading, setWorkspace };
}
