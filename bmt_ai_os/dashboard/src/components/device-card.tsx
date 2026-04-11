"use client";

import { useState } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
  CardFooter,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { deployModel, type FleetDevice } from "@/lib/api";

interface DeviceCardProps {
  device: FleetDevice;
  availableModels: string[];
}

function formatLastSeen(lastSeen: string): string {
  if (!lastSeen) return "Never";
  const diff = Date.now() - new Date(lastSeen).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function UsageBar({
  value,
  label,
}: {
  value: number;
  label: string;
}) {
  const pct = Math.min(100, Math.max(0, value));
  const color =
    pct >= 90
      ? "bg-red-500"
      : pct >= 70
        ? "bg-yellow-500"
        : "bg-green-500";

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>{label}</span>
        <span>{pct.toFixed(0)}%</span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-muted">
        <div
          className={`h-1.5 rounded-full transition-all ${color}`}
          style={{ width: `${pct}%` }}
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={label}
        />
      </div>
    </div>
  );
}

export function DeviceCard({ device, availableModels }: DeviceCardProps) {
  const [selectedModel, setSelectedModel] = useState("");
  const [deploying, setDeploying] = useState(false);
  const [deployResult, setDeployResult] = useState<string | null>(null);
  const [showDeploy, setShowDeploy] = useState(false);

  async function handleDeploy() {
    if (!selectedModel) return;
    setDeploying(true);
    setDeployResult(null);
    try {
      await deployModel({ model: selectedModel, device_ids: [device.device_id] });
      setDeployResult(`Queued: ${selectedModel}`);
      setShowDeploy(false);
      setSelectedModel("");
    } catch {
      setDeployResult("Deploy failed");
    } finally {
      setDeploying(false);
    }
  }

  const boardLabel = device.board || device.arch || "Unknown board";

  return (
    <Card className="flex flex-col">
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <CardTitle className="truncate font-mono text-sm">
              {device.hostname || device.device_id}
            </CardTitle>
            <CardDescription className="mt-0.5 truncate text-xs">
              {boardLabel}
            </CardDescription>
          </div>

          {/* Online/offline indicator */}
          <div className="flex shrink-0 items-center gap-1.5">
            <span
              className={`size-2 rounded-full ${device.online ? "bg-green-500" : "bg-red-500"}`}
              aria-label={device.online ? "Online" : "Offline"}
            />
            <Badge
              variant={device.online ? "default" : "destructive"}
              className="text-[10px]"
            >
              {device.online ? "online" : "offline"}
            </Badge>
          </div>
        </div>
      </CardHeader>

      <CardContent className="flex flex-col gap-3">
        {/* Resource usage */}
        <div className="space-y-2">
          <UsageBar value={device.cpu_percent} label="CPU" />
          <UsageBar value={device.memory_percent} label="Memory" />
        </div>

        {/* Loaded models */}
        <div>
          <p className="mb-1.5 text-xs font-medium text-muted-foreground">
            Models loaded
          </p>
          {device.loaded_models.length === 0 ? (
            <p className="text-xs text-muted-foreground/60">None</p>
          ) : (
            <div className="flex flex-wrap gap-1">
              {device.loaded_models.map((m) => (
                <Badge key={m} variant="secondary" className="font-mono text-[10px]">
                  {m}
                </Badge>
              ))}
            </div>
          )}
        </div>

        {/* Last heartbeat */}
        <p className="text-xs text-muted-foreground">
          Last seen:{" "}
          <span className="font-medium text-foreground">
            {formatLastSeen(device.last_seen)}
          </span>
        </p>

        {/* Deploy result feedback */}
        {deployResult && (
          <p
            className={`text-xs ${deployResult.startsWith("Queued") ? "text-green-500" : "text-destructive"}`}
          >
            {deployResult}
          </p>
        )}
      </CardContent>

      <CardFooter className="mt-auto gap-2">
        {!showDeploy ? (
          <Button
            variant="outline"
            size="sm"
            className="w-full"
            onClick={() => {
              setShowDeploy(true);
              setDeployResult(null);
            }}
            disabled={!device.online}
          >
            Deploy Model
          </Button>
        ) : (
          <div className="flex w-full flex-col gap-2">
            <select
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              className="flex h-8 w-full rounded-lg border border-input bg-background px-3 py-1 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50"
              aria-label="Select model to deploy"
            >
              <option value="">Select model…</option>
              {availableModels.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>

            <div className="flex gap-2">
              <Button
                size="sm"
                className="flex-1"
                onClick={handleDeploy}
                disabled={!selectedModel || deploying}
              >
                {deploying ? "Queuing…" : "Confirm"}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setShowDeploy(false);
                  setSelectedModel("");
                }}
                disabled={deploying}
              >
                Cancel
              </Button>
            </div>
          </div>
        )}
      </CardFooter>
    </Card>
  );
}
