import { apiFetch } from "./client";

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  username: string;
  role: string;
}

export interface SshKeySummary {
  name: string;
  fingerprint: string;
  created_at: string;
}

export async function login(req: LoginRequest): Promise<LoginResponse> {
  return apiFetch<LoginResponse>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function logout(): Promise<void> {
  try {
    await apiFetch("/api/v1/auth/logout", { method: "POST" });
  } finally {
    if (typeof window !== "undefined") {
      localStorage.removeItem("bmt_auth_token");
      localStorage.removeItem("bmt_auth_user");
    }
  }
}

export async function fetchMe(): Promise<{ username: string; role: string }> {
  return apiFetch("/api/v1/auth/me");
}

export async function fetchSshKeys(): Promise<SshKeySummary[]> {
  return apiFetch<SshKeySummary[]>("/api/v1/ssh-keys");
}

export async function uploadSshKey(
  name: string,
  key: string,
): Promise<SshKeySummary> {
  return apiFetch<SshKeySummary>("/api/v1/ssh-keys", {
    method: "POST",
    body: JSON.stringify({ name, key }),
  });
}

export async function deleteSshKey(
  name: string,
): Promise<{ deleted: boolean; name: string }> {
  return apiFetch<{ deleted: boolean; name: string }>(
    `/api/v1/ssh-keys/${encodeURIComponent(name)}`,
    { method: "DELETE" },
  );
}
