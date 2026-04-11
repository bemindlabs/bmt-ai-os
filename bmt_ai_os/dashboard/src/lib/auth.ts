const TOKEN_KEY = "bmt_auth_token";
const USER_KEY = "bmt_auth_user";

export interface AuthUser {
  username: string;
  role: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  username?: string;
  role?: string;
}

export async function login(username: string, password: string): Promise<void> {
  const res = await fetch("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Login failed: ${res.status}`);
  }

  const data = (await res.json()) as LoginResponse;

  if (!data.access_token) {
    throw new Error("No access token in response");
  }

  localStorage.setItem(TOKEN_KEY, data.access_token);

  const user: AuthUser = {
    username: data.username ?? username,
    role: data.role ?? "viewer",
  };
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export async function logout(): Promise<void> {
  const token = getToken();

  // Best-effort — ignore network errors on logout
  if (token) {
    try {
      await fetch("/api/v1/auth/logout", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
      });
    } catch {
      // Ignore
    }
  }

  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function getUser(): AuthUser | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

export function isAuthenticated(): boolean {
  return getToken() !== null;
}
