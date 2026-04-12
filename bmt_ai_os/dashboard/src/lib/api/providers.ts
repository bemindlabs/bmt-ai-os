import { apiFetch } from "./client";

export interface Provider {
  name: string;
  healthy: boolean;
  active?: boolean;
  discovered?: boolean;
  latency_ms?: number;
  latency_history?: number[];
  error_count?: number;
  cooldown_remaining_s?: number;
  last_success_ts?: number | null;
  [key: string]: unknown;
}

export interface DiscoveredProvider {
  name: string;
  port: number;
  base_url: string;
  provider_type: string;
  latency_ms: number;
  already_registered: boolean;
  registered_now: boolean;
  discovered: true;
  error: string | null;
  discovered_at: number;
}

export interface DiscoverResponse {
  discovered: DiscoveredProvider[];
  count: number;
}

export interface ProvidersResponse {
  providers: Provider[];
  active?: string;
}

export type CredentialType = "api_key" | "oauth" | "token";

export interface ProviderKey {
  id: string;
  provider_name: string;
  masked_key: string;
  credential_type: CredentialType;
  display_name?: string;
  expires_at?: number | null;
  usage_count: number;
  last_used: number | null;
  last_error: string | null;
  cooldown_until: number | null;
  status: "active" | "cooldown" | "expired";
}

export interface ProviderKeysResponse {
  provider_name: string;
  keys: ProviderKey[];
  total: number;
}

export interface AddKeyResponse {
  provider_name: string;
  key: ProviderKey;
}

export async function fetchProviders(): Promise<ProvidersResponse> {
  const raw = await apiFetch<{ providers: Record<string, unknown>[]; active?: string }>(
    "/api/v1/providers",
  );
  return {
    ...raw,
    providers: raw.providers.map((p) => {
      const health = p.health as Record<string, unknown> | undefined;
      return {
        ...p,
        name: p.name as string,
        healthy:
          typeof p.healthy === "boolean"
            ? p.healthy
            : !!(health?.healthy),
        active: p.active as boolean | undefined,
        discovered: p.discovered as boolean | undefined,
        latency_ms:
          (health?.latency_ms as number | undefined) ??
          (p.latency_ms as number | undefined),
        latency_history: p.latency_history as number[] | undefined,
        error_count: p.error_count as number | undefined,
        cooldown_remaining_s: p.cooldown_remaining_s as number | undefined,
        last_success_ts: p.last_success_ts as number | null | undefined,
      };
    }),
  };
}

export async function discoverProviders(): Promise<DiscoverResponse> {
  return apiFetch<DiscoverResponse>("/api/v1/providers/discover");
}

export async function setActiveProvider(name: string): Promise<unknown> {
  return apiFetch<unknown>("/api/v1/providers/active", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export async function setFallbackOrder(order: string[]): Promise<{ order: string[] }> {
  return apiFetch("/api/v1/providers/fallback-order", {
    method: "PUT",
    body: JSON.stringify({ order }),
  });
}

export async function fetchProviderKeys(
  providerName: string,
): Promise<ProviderKeysResponse> {
  return apiFetch<ProviderKeysResponse>(
    `/api/v1/providers/config/${encodeURIComponent(providerName)}/keys`,
  );
}

export async function addProviderKey(
  providerName: string,
  apiKey: string,
  credentialType: CredentialType = "api_key",
  displayName = "",
): Promise<AddKeyResponse> {
  return apiFetch<AddKeyResponse>(
    `/api/v1/providers/config/${encodeURIComponent(providerName)}/keys`,
    {
      method: "POST",
      body: JSON.stringify({
        api_key: apiKey,
        credential_type: credentialType,
        display_name: displayName,
      }),
    },
  );
}

export async function deleteProviderKey(
  providerName: string,
  keyId: string,
): Promise<{ deleted: boolean; key_id: string; provider_name: string }> {
  return apiFetch(
    `/api/v1/providers/config/${encodeURIComponent(providerName)}/keys/${encodeURIComponent(keyId)}`,
    { method: "DELETE" },
  );
}

/** Compact alias used by editor AI panel (BMTOS-150). */
export async function saveProviderKey(
  provider: string,
  key: string,
): Promise<{ status: string }> {
  const res = await addProviderKey(provider, key);
  return { status: res.key.status };
}

// ---------------------------------------------------------------------------
// OAuth
// ---------------------------------------------------------------------------

export interface OAuthStartResponse {
  auth_url: string;
  state: string;
  provider: string;
}

export interface OAuthCallbackResponse {
  provider_name: string;
  credential_type: "oauth";
  key: ProviderKey;
  expires_in: number;
}

export interface OAuthStatusResponse {
  provider_name: string;
  oauth_supported: boolean;
  oauth_configured: boolean;
  oauth_valid: boolean;
  has_client_config: boolean;
  credentials: ProviderKey[];
}

export async function oauthStart(
  providerName: string,
  redirectUri: string,
  clientId?: string,
  clientSecret?: string,
): Promise<OAuthStartResponse> {
  return apiFetch<OAuthStartResponse>(
    `/api/v1/providers/config/${encodeURIComponent(providerName)}/oauth/start`,
    {
      method: "POST",
      body: JSON.stringify({
        redirect_uri: redirectUri,
        client_id: clientId || undefined,
        client_secret: clientSecret || undefined,
      }),
    },
  );
}

export async function oauthCallback(
  providerName: string,
  code: string,
  state: string,
  redirectUri?: string,
): Promise<OAuthCallbackResponse> {
  return apiFetch<OAuthCallbackResponse>(
    `/api/v1/providers/config/${encodeURIComponent(providerName)}/oauth/callback`,
    {
      method: "POST",
      body: JSON.stringify({
        code,
        state,
        redirect_uri: redirectUri || undefined,
      }),
    },
  );
}

export async function oauthStatus(
  providerName: string,
): Promise<OAuthStatusResponse> {
  return apiFetch<OAuthStatusResponse>(
    `/api/v1/providers/config/${encodeURIComponent(providerName)}/oauth/status`,
  );
}
