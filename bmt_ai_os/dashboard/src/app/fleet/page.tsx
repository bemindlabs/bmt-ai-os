"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Terminal,
  Cpu,
  MemoryStick,
  HardDrive,
  RefreshCw,
  Server,
  Wifi,
  WifiOff,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { fetchFleetDevices } from "@/lib/api";
import type { FleetDevice } from "@/lib/api";

const REFRESH_INTERVAL_MS = 30_000;

// ─── Sub-components ──────────────────────────────────────────────────────────

function StatusBadge({ online }: { online: boolean }) {
  return online ? (
    <Badge className="bg-green-600 text-white hover:bg-green-600">
      <Wifi className="mr-1 size-3" />
      Online
    </Badge>
  ) : (
    <Badge variant="secondary">
      <WifiOff className="mr-1 size-3" />
      Offline
    </Badge>
  );
}

function ResourceBar({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ElementType;
  label: string;
  value: number;
}) {
  const pct = Math.min(Math.max(value, 0), 100);
  const indicatorClass =
    pct > 90
      ? "[&>div]:bg-red-500"
      : pct > 70
        ? "[&>div]:bg-yellow-500"
        : "[&>div]:bg-green-500";

  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <Icon className="size-3 shrink-0" />
      <span className="w-8 shrink-0">{label}</span>
      <Progress value={pct} className={cn("h-1.5 w-20", indicatorClass)} />
      <span className="w-8 text-right tabular-nums">{pct.toFixed(0)}%</span>
    </div>
  );
}

function SkeletonRow() {
  return (
    <TableRow>
      {Array.from({ length: 7 }).map((_, i) => (
        <TableCell key={i}>
          <div className="h-4 animate-pulse rounded bg-muted" />
        </TableCell>
      ))}
    </TableRow>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center gap-3 py-16 text-center">
      <div className="flex size-14 items-center justify-center rounded-full bg-muted">
        <Server className="size-7 text-muted-foreground" />
      </div>
      <p className="text-sm font-medium">No devices registered</p>
      <p className="max-w-xs text-xs text-muted-foreground">
        Fleet agents running on edge devices will appear here once they send
        their first heartbeat.
      </p>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function FleetPage() {
  const router = useRouter();
  const [devices, setDevices] = useState<FleetDevice[]>([]);
  const [total, setTotal] = useState(0);
  const [online, setOnline] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchFleetDevices();
      setDevices(data.devices);
      setTotal(data.total);
      setOnline(data.online);
      setLastRefresh(new Date());
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to fetch fleet data",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const interval = setInterval(() => void load(), REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [load]);

  function openSsh(device: FleetDevice) {
    const host = device.hostname || device.device_id;
    const params = new URLSearchParams({ host, user: "root" });
    router.push(`/terminal?${params.toString()}`);
  }

  const isInitialLoad = loading && devices.length === 0;

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Fleet</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Registered edge devices and their current status. Auto-refreshes
            every 30s.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {lastRefresh && (
            <span className="text-xs text-muted-foreground">
              {lastRefresh.toLocaleTimeString()}
            </span>
          )}
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            <RefreshCw
              className={cn("mr-1.5 size-3.5", loading && "animate-spin")}
            />
            Refresh
          </Button>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Total Devices</CardDescription>
            <CardTitle className="text-3xl">
              {isInitialLoad ? (
                <div className="h-9 w-12 animate-pulse rounded bg-muted" />
              ) : (
                total
              )}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Online</CardDescription>
            <CardTitle className="text-3xl text-green-500">
              {isInitialLoad ? (
                <div className="h-9 w-12 animate-pulse rounded bg-muted" />
              ) : (
                online
              )}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Offline</CardDescription>
            <CardTitle className="text-3xl text-muted-foreground">
              {isInitialLoad ? (
                <div className="h-9 w-12 animate-pulse rounded bg-muted" />
              ) : (
                total - online
              )}
            </CardTitle>
          </CardHeader>
        </Card>
      </div>

      {/* Device table */}
      <Card>
        <CardHeader>
          <CardTitle>Devices</CardTitle>
          <CardDescription>
            {error
              ? "Could not reach fleet API."
              : isInitialLoad
                ? "Loading devices…"
                : `${devices.length} device${devices.length !== 1 ? "s" : ""} registered`}
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {/* Error banner */}
          {error && (
            <p className="px-6 py-4 text-sm text-red-500">{error}</p>
          )}

          {/* Skeleton rows on initial load */}
          {isInitialLoad && !error && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Device</TableHead>
                  <TableHead>Board / Arch</TableHead>
                  <TableHead>OS</TableHead>
                  <TableHead>Resources</TableHead>
                  <TableHead>Models</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <SkeletonRow />
                <SkeletonRow />
                <SkeletonRow />
              </TableBody>
            </Table>
          )}

          {/* Empty state */}
          {!isInitialLoad && !error && devices.length === 0 && <EmptyState />}

          {/* Device rows */}
          {devices.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Device</TableHead>
                  <TableHead>Board / Arch</TableHead>
                  <TableHead>OS</TableHead>
                  <TableHead>Resources</TableHead>
                  <TableHead>Models</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {devices.map((device) => (
                  <TableRow key={device.device_id}>
                    {/* Device identity */}
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Server className="size-4 shrink-0 text-muted-foreground" />
                        <div>
                          <div className="font-medium">
                            {device.hostname || device.device_id}
                          </div>
                          <div className="font-mono text-xs text-muted-foreground">
                            {device.device_id}
                          </div>
                        </div>
                      </div>
                    </TableCell>

                    {/* Board / Arch */}
                    <TableCell className="text-sm">
                      <div>{device.board || "—"}</div>
                      <div className="text-xs text-muted-foreground">
                        {device.arch || "—"}
                      </div>
                    </TableCell>

                    {/* OS */}
                    <TableCell className="text-xs text-muted-foreground">
                      {device.os_version || "—"}
                    </TableCell>

                    {/* Resource bars */}
                    <TableCell>
                      <div className="space-y-1">
                        <ResourceBar
                          icon={Cpu}
                          label="CPU"
                          value={device.cpu_percent ?? 0}
                        />
                        <ResourceBar
                          icon={MemoryStick}
                          label="RAM"
                          value={device.memory_percent ?? 0}
                        />
                        <ResourceBar
                          icon={HardDrive}
                          label="Disk"
                          value={device.disk_percent ?? 0}
                        />
                      </div>
                    </TableCell>

                    {/* Loaded models */}
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {(device.loaded_models ?? []).length === 0 ? (
                          <span className="text-xs text-muted-foreground">
                            none
                          </span>
                        ) : (
                          (device.loaded_models ?? []).slice(0, 3).map((m) => (
                            <Badge key={m} variant="outline" className="text-xs">
                              {m}
                            </Badge>
                          ))
                        )}
                        {(device.loaded_models ?? []).length > 3 && (
                          <Badge variant="secondary" className="text-xs">
                            +{(device.loaded_models ?? []).length - 3}
                          </Badge>
                        )}
                      </div>
                    </TableCell>

                    {/* Status */}
                    <TableCell>
                      <StatusBadge online={device.online ?? false} />
                    </TableCell>

                    {/* Actions */}
                    <TableCell className="text-right">
                      {device.online && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => openSsh(device)}
                          title="Open SSH terminal to this device"
                        >
                          <Terminal className="mr-1.5 size-3.5" />
                          SSH
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
