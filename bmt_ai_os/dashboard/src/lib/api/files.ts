import { apiFetch } from "./client";

export type Breadcrumb = { name: string; path: string };

export interface FileEntry {
  name: string;
  path: string;
  is_dir: boolean;
  size: number;
  modified: string;
}

export async function listFiles(
  path: string,
): Promise<{ entries: FileEntry[]; breadcrumbs: Breadcrumb[] }> {
  return apiFetch(`/api/v1/files/list?path=${encodeURIComponent(path)}`);
}

export async function readFile(
  path: string,
): Promise<{ content: string; path: string }> {
  return apiFetch(`/api/v1/files/read?path=${encodeURIComponent(path)}`);
}

export function downloadFileUrl(path: string): string {
  return `/api/v1/files/download?path=${encodeURIComponent(path)}`;
}

export async function writeFile(
  path: string,
  content: string,
): Promise<{ status: string; path: string; size: number }> {
  return apiFetch("/api/v1/files/write", {
    method: "PUT",
    body: JSON.stringify({ path, content }),
  });
}

export async function uploadFile(
  path: string,
  file: File,
): Promise<{ status: string }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(
    `/api/v1/files/upload?path=${encodeURIComponent(path)}`,
    { method: "POST", body: form },
  );
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export async function createDirectory(path: string): Promise<{ status: string }> {
  return apiFetch("/api/v1/files/mkdir", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}

export async function renameFile(
  oldPath: string,
  newPath: string,
): Promise<{ status: string }> {
  return apiFetch("/api/v1/files/rename", {
    method: "POST",
    body: JSON.stringify({ old_path: oldPath, new_path: newPath }),
  });
}

export async function deleteFile(path: string): Promise<{ status: string }> {
  return apiFetch(
    `/api/v1/files/delete?path=${encodeURIComponent(path)}`,
    { method: "DELETE" },
  );
}

export async function ingestPath(path: string): Promise<{ status: string }> {
  return apiFetch("/api/v1/ingest", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}
