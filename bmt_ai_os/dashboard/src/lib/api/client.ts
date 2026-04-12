export const BASE_URL =
  typeof window === "undefined"
    ? (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080")
    : "";

export function getAuthHeader(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const token = localStorage.getItem("bmt_auth_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...getAuthHeader(),
      ...(init?.headers ?? {}),
    },
    // Do not cache — data should be fresh
    cache: "no-store",
  });

  if (res.status === 401 && typeof window !== "undefined") {
    // Clear stale credentials and redirect to login
    localStorage.removeItem("bmt_auth_token");
    localStorage.removeItem("bmt_auth_user");
    window.location.replace("/login");
    throw new Error("Session expired");
  }

  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${res.statusText}`);
  }

  return res.json() as Promise<T>;
}
