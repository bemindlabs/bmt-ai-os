"use client";

import { useState, useEffect, useCallback } from "react";
import {
  fetchFleetDevices,
  fetchFleetSummary,
  fetchModels,
  type FleetDevice,
  type FleetSummary,
} from "@/lib/api";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { DeviceCard } from "@/components/device-card";
import { Server, Wifi, WifiOff, Layers } from "lucide-react";

const REFRESH_INTERVAL_MS = 10_000;

interface SummaryStatProps {
  icon: React.ReactNode;
  label: string;
  value: number | string;
}

function SummaryStat({ icon, label, value }: SummaryStatProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2 text-muted-foreground">
          {icon}
          <span className="text-xs font-medium uppercase tracking-wide">
            {label}
          </span>
        </div>
      </CardHeader>
      <CardContent>
        <p className="text-2xl font-semibold tabular-nums">{value}</p>
      </CardContent>
    </Card>
  );
}

export default function FleetPage() {
  const [devices, setDevices] = useState<FleetDevice[]>([]);
  const [summary, setSummary] = useState<FleetSummary | null>(null);
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [devicesRes, summaryRes] = await Promise.all([
        fetchFleetDevices().catch(() => null),
        fetchFleetSummary().catch(() => null),
      ]);

      if (devicesRes) setDevices(devicesRes.devices ?? []);
      if (summaryRes) setSummary(summaryRes);
      setError(null);
      setLastRefreshed(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch fleet data");
    }
  }, []);

  // Load available models once for the deploy dropdown
  useEffect(() => {
    fetchModels()
      .then((res) => setAvailableModels(res.models.map((m) => m.name)))
      .catch(() => {});
  }, []);

  // Initial load + auto-refresh every 10 s
  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [refresh]);

  const onlineCount = summary?.online_devices ?? devices.filter((d) => d.online).length;
  const offlineCount =
    summary?.offline_devices ?? devices.filter((d) => !d.online).length;
  const totalModels = summary?.total_models ?? 0;

  return (
    <div className="space-y-8">
      {/* Page heading */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Fleet</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            All registered devices and their current status.
          </p>
        </div>
        {lastRefreshed && (
          <p className="shrink-0 text-xs text-muted-foreground">
            Updated {lastRefreshed.toLocaleTimeString()}
          </p>
        )}
      </div>

      {/* Error banner */}
      {error && (
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive"
        >
          {error}
        </div>
      )}

      {/* Summary stats */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <SummaryStat
          icon={<Server className="size-4" />}
          label="Total devices"
          value={summary?.total_devices ?? devices.length}
        />
        <SummaryStat
          icon={<Wifi className="size-4 text-green-500" />}
          label="Online"
          value={onlineCount}
        />
        <SummaryStat
          icon={<WifiOff className="size-4 text-red-500" />}
          label="Offline"
          value={offlineCount}
        />
        <SummaryStat
          icon={<Layers className="size-4" />}
          label="Total models"
          value={totalModels}
        />
      </div>

      {/* Device grid */}
      {devices.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center">
            <Server className="mx-auto mb-3 size-8 text-muted-foreground/40" />
            <p className="text-sm text-muted-foreground">
              {error
                ? "Could not load devices."
                : "No devices registered yet."}
            </p>
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-medium">Devices</h2>
            <Badge variant="secondary">{devices.length}</Badge>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {devices.map((device) => (
              <DeviceCard
                key={device.device_id}
                device={device}
                availableModels={availableModels}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
