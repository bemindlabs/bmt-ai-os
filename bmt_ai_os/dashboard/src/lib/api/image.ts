import { apiFetch } from "./client";

// ── Types ──────────────────────────────────────────────────────────────────

export interface HardwareTarget {
  id: string;
  name: string;
  description: string;
  arch: string;
  accelerator: string;
  default_tier: string;
  image_format: string;
  min_storage_gb: number;
  specs: Record<string, string>;
}

export interface ToolPackage {
  id: string;
  name: string;
  description: string;
  category: string;
  size_mb: number;
  arm64: boolean;
  required: boolean;
  tier_minimum: string;
  dependencies: string[];
  ports: number[];
  tags: string[];
}

export interface DeviceTier {
  id: string;
  name: string;
  description: string;
  min_ram_gb: number;
  max_ram_gb: number;
  default_model: string;
  max_image_size_gb: number;
}

export interface BuildPreset {
  id: string;
  name: string;
  description: string;
  packages: string[];
}

export interface BuildProfile {
  id: string;
  name: string;
  target: string;
  tier: string;
  packages: string[];
  description: string;
  preset: string | null;
  custom_options: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ValidationResult {
  resolved_packages: string[];
  warnings: string[];
  estimated_size_mb: number;
  valid: boolean;
}

export interface BuildStatus {
  id: string;
  profile_id: string;
  status: "pending" | "running" | "completed" | "failed";
  manifest_path: string;
  started_at: string;
  completed_at: string | null;
  log: string[];
  error: string | null;
}

// ── API calls ──────────────────────────────────────────────────────────────

export async function fetchTargets(): Promise<{ targets: HardwareTarget[] }> {
  return apiFetch("/api/v1/image/targets");
}

export async function fetchPackages(
  category?: string,
): Promise<{ packages: ToolPackage[]; categories: string[] }> {
  const query = category ? `?category=${encodeURIComponent(category)}` : "";
  return apiFetch(`/api/v1/image/packages${query}`);
}

export async function fetchTiers(): Promise<{ tiers: DeviceTier[] }> {
  return apiFetch("/api/v1/image/tiers");
}

export async function fetchPresets(): Promise<{ presets: BuildPreset[] }> {
  return apiFetch("/api/v1/image/presets");
}

export async function fetchProfiles(): Promise<{ profiles: BuildProfile[] }> {
  return apiFetch("/api/v1/image/profiles");
}

export async function createProfile(req: {
  name: string;
  target: string;
  tier: string;
  packages: string[];
  description?: string;
  preset?: string;
}): Promise<{
  profile: BuildProfile;
  resolved_packages: string[];
  warnings: string[];
  estimated_size_mb: number;
}> {
  return apiFetch("/api/v1/image/profiles", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function deleteProfile(profileId: string): Promise<void> {
  await apiFetch(`/api/v1/image/profiles/${profileId}`, { method: "DELETE" });
}

export async function validateSelection(req: {
  target: string;
  tier: string;
  packages: string[];
}): Promise<ValidationResult> {
  return apiFetch("/api/v1/image/validate", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function triggerBuild(
  profileId: string,
): Promise<{ build_id: string; status: string; manifest_path: string }> {
  return apiFetch("/api/v1/image/build", {
    method: "POST",
    body: JSON.stringify({ profile_id: profileId }),
  });
}

export async function fetchBuildStatus(buildId: string): Promise<BuildStatus> {
  return apiFetch(`/api/v1/image/builds/${buildId}`);
}
