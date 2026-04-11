"use client";

import { useEffect, useState } from "react";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Terminal, Cpu, MemoryStick, HardDrive, RefreshCw } from "lucide-react";
import { fetchFleetDevices, FleetDevice } from "@/lib/api";

function StatusBadge({ online }: { online: boolean }) {
  return online ? (
    <Badge className="bg-green-600 text-white hover:bg-green-600">Online</Badge>
  ) : (
    <Badge variant="secondary">Offline</Badge>
  );
}

function PercentBar({ value, label }: { value: number; label: string }) {
  const color =
    value > 90 ? "bg-red-500" : value > 70 ? "bg-yellow-500" : "bg-green-500";
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <span className="w-8 shrink-0">{label}</span>
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-muted">
        <div
          className={`h-full ${color} transition-all`}
          style={{ width: `${Math.min(value, 100)}%` }}
        />
      </div>
      <span className="w-8 text-right">{value.toFixed(0)}%</span>
    </div>
  );
}

export default function FleetPage() {
  const router = useRouter();
  const [devices, setDevices] = useState<FleetDevice[]>([]);
  const [total, setTotal] = useState(0);
  const [online, setOnline] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchFleetDevices();
      setDevices(data.devices);
      setTotal(data.total);
      setOnline(data.online);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch fleet data");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const interval = setInterval(load, 15_000);
    return () => clearInterval(interval);
  }, []);

  function openSsh(device: FleetDevice) {
    const host = device.hostname || device.device_id;
    const params = new URLSearchParams({ host, user: "root" });
    router.push(`/terminal?${params.toString()}`);
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Fleet</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Registered edge devices and their current status.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`mr-2 size-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Total Devices</CardDescription>
            <CardTitle className="text-3xl">{total}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Online</CardDescription>
            <CardTitle className="text-3xl text-green-500">{online}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Offline</CardDescription>
            <CardTitle className="text-3xl text-muted-foreground">
              {total - online}
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
              : loading && devices.length === 0
                ? "Loading devices…"
                : devices.length === 0
                  ? "No devices registered yet."
                  : `${devices.length} device${devices.length !== 1 ? "s" : ""} registered`}
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {error && (
            <p className="px-6 py-4 text-sm text-red-500">{error}</p>
          )}
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
                    <TableCell>
                      <div className="font-medium">{device.hostname || device.device_id}</div>
                      <div className="font-mono text-xs text-muted-foreground">
                        {device.device_id}
                      </div>
                    </TableCell>
                    <TableCell className="text-sm">
                      <div>{device.board || "—"}</div>
                      <div className="text-xs text-muted-foreground">{device.arch || "—"}</div>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {device.os_version || "—"}
                    </TableCell>
                    <TableCell>
                      <div className="space-y-0.5">
                        <PercentBar value={device.cpu_percent ?? 0} label="CPU" />
                        <PercentBar value={device.memory_percent ?? 0} label="RAM" />
                        <PercentBar value={device.disk_percent ?? 0} label="Disk" />
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {(device.loaded_models ?? []).length === 0 ? (
                          <span className="text-xs text-muted-foreground">none</span>
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
                    <TableCell>
                      <StatusBadge online={device.online ?? false} />
                    </TableCell>
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
