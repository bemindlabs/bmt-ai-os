import { apiFetch } from "./client";

export interface FleetDevice {
  device_id: string;
  hostname: string;
  arch: string;
  board: string;
  os_version: string;
  online: boolean;
  cpu_percent: number;
  memory_percent: number;
  disk_percent: number;
  loaded_models: string[];
  registered_at?: string;
  last_seen?: string;
  [key: string]: unknown;
}

export interface FleetDevicesResponse {
  devices: FleetDevice[];
  total: number;
  online: number;
}

export async function fetchFleetDevices(): Promise<FleetDevicesResponse> {
  return apiFetch<FleetDevicesResponse>("/api/v1/fleet/devices");
}

export async function deployModel(req: {
  model: string;
  device_ids: string[];
}): Promise<{ status: string; targeted_devices: string[]; device_count: number }> {
  return apiFetch("/api/v1/fleet/deploy-model", {
    method: "POST",
    body: JSON.stringify(req),
  });
}
