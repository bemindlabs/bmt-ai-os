"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  Activity,
  Server,
  Clock,
  Zap,
  AlertTriangle,
  RefreshCw,
  MessageSquare,
  Code2,
  BrainCircuit,
  Terminal,
  WifiOff,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  CardAction,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  fetchStatus,
  fetchMetrics,
  formatUptime,
  type StatusResponse,
  type MetricsResponse,
  type ServiceStatus,
} from "@/lib/api";

// ── helpers ──────────────────────────────────────────────────────────────────

function healthColor(health: string): string {
  if (health === "healthy") return "bg-green-500";
  if (health === "degraded") return "bg-yellow-500";
  return "bg-red-500";
}

function healthVariant(
  health: string
): "default" | "outline" | "destructive" | "secondary" {
  if (health === "healthy") return "default";
  if (health === "degraded") return "outline";
  return "destructive";
}

function circuitBreakerLabel(state?: string): string | null {
  if (!state || state === "closed") return null;
  return state === "open" ? "Circuit Open" : "Half-Open";
}

// ── sub-components ────────────────────────────────────────────────────────────

function ServiceCard({ svc }: { svc: ServiceStatus }) {
  const healthy = svc.health === "healthy";
  const degraded = svc.health === "degraded";
  const cbLabel = circuitBreakerLabel(svc.circuit_breaker);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2.5">
          <span
            className={`size-2.5 shrink-0 rounded-full ${healthColor(svc.health)} ${
              healthy ? "shadow-[0_0_6px_1px] shadow-green-500/60" : ""
            }`}
          />
          <CardTitle className="text-sm font-medium">{svc.name}</CardTitle>
        </div>
        <CardAction>
          <Badge variant={healthVariant(svc.health)} className="capitalize">
            {svc.health}
          </Badge>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-2">
        {/* Uptime */}
        {svc.uptime_seconds != null && (
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Clock className="size-3 shrink-0" />
            <span>Up {formatUptime(svc.uptime_seconds)}</span>
          </div>
        )}

        {/* Restarts */}
        {svc.restarts != null && svc.restarts > 0 && (
          <div className="flex items-center gap-1.5 text-xs text-yellow-500">
            <AlertTriangle className="size-3 shrink-0" />
            <span>{svc.restarts} restart{svc.restarts !== 1 ? "s" : ""}</span>
          </div>
        )}

        {/* Circuit breaker */}
        {cbLabel && (
          <Badge variant="destructive" className="text-xs">
            {cbLabel}
          </Badge>
        )}

        {/* Last check latency */}
        {svc.last_check_ms != null && (
          <p className="text-xs text-muted-foreground">
            Last check: {svc.last_check_ms.toFixed(0)} ms
          </p>
        )}

        {/* Last error */}
        {!healthy && svc.last_error && (
          <p className="truncate text-xs text-destructive" title={svc.last_error}>
            {svc.last_error}
          </p>
        )}

        {/* State indicator for degraded */}
        {degraded && (
          <Progress
            value={50}
            className="h-1 [&>div]:bg-yellow-500"
            aria-label="Service degraded"
          />
        )}
      </CardContent>
    </Card>
  );
}

function StatCard({
  label,
  value,
  sub,
  icon: Icon,
  warn,
}: {
  label: string;
  value: string;
  sub?: string;
  icon: React.ComponentType<{ className?: string }>;
  warn?: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardDescription>{label}</CardDescription>
          <Icon
            className={`size-4 ${warn ? "text-destructive" : "text-muted-foreground"}`}
          />
        </div>
        <CardTitle
          className={`text-2xl tabular-nums ${warn ? "text-destructive" : ""}`}
        >
          {value}
        </CardTitle>
      </CardHeader>
      {sub && (
        <CardContent>
          <p
            className={`text-xs ${warn ? "text-destructive" : "text-muted-foreground"}`}
          >
            {sub}
          </p>
        </CardContent>
      )}
    </Card>
  );
}

const QUICK_ACTIONS = [
  { href: "/chat", label: "Chat", icon: MessageSquare, desc: "Talk to AI" },
  { href: "/editor", label: "Editor", icon: Code2, desc: "AI code editor" },
  { href: "/models", label: "Models", icon: BrainCircuit, desc: "Manage models" },
  { href: "/terminal", label: "Terminal", icon: Terminal, desc: "SSH terminal" },
] as const;

// ── page ──────────────────────────────────────────────────────────────────────

export default function OverviewPage() {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [statusResult, metricsResult] = await Promise.allSettled([
        fetchStatus(),
        fetchMetrics(),
      ]);
      setStatus(
        statusResult.status === "fulfilled" ? statusResult.value : null
      );
      setMetrics(
        metricsResult.status === "fulfilled" ? metricsResult.value : null
      );
      if (
        statusResult.status === "rejected" &&
        metricsResult.status === "rejected"
      ) {
        setError("Controller API is unreachable");
      }
      setLastRefreshed(new Date());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const interval = setInterval(load, 30_000);
    return () => clearInterval(interval);
  }, [load]);

  // Fall back to placeholder services when API is down
  const coreServices: ServiceStatus[] = status?.services ?? [
    { name: "Ollama", health: "unknown" },
    { name: "ChromaDB", health: "unknown" },
    { name: "Controller", health: "unknown" },
  ];

  const errorRate = metrics?.error_rate ?? null;
  const errorRateWarn = errorRate != null && errorRate > 0.05;

  const healthyCount = coreServices.filter(
    (s) => s.health === "healthy"
  ).length;
  const overallHealthy =
    status !== null && healthyCount === coreServices.length;
  const overallDegraded =
    status !== null &&
    !overallHealthy &&
    coreServices.some((s) => s.health !== "unknown");

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold">System Overview</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Live status of AI stack services and runtime metrics.
            {lastRefreshed && (
              <span className="ml-2 text-xs">
                Updated {lastRefreshed.toLocaleTimeString()}
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* Overall health pill */}
          {error ? (
            <Badge variant="destructive" className="gap-1">
              <WifiOff className="size-3" />
              Unreachable
            </Badge>
          ) : overallHealthy ? (
            <Badge className="gap-1 bg-green-600 text-white hover:bg-green-600">
              <span className="size-1.5 rounded-full bg-white" />
              All Systems Operational
            </Badge>
          ) : overallDegraded ? (
            <Badge variant="outline" className="gap-1 border-yellow-500 text-yellow-500">
              <AlertTriangle className="size-3" />
              Degraded
            </Badge>
          ) : null}

          <Button
            variant="outline"
            size="sm"
            onClick={load}
            disabled={loading}
            aria-label="Refresh data"
          >
            <RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* API unreachable banner */}
      {error && (
        <Card className="border-destructive/50 bg-destructive/5">
          <CardContent className="flex items-center gap-3 py-4">
            <WifiOff className="size-5 shrink-0 text-destructive" />
            <div>
              <p className="text-sm font-medium text-destructive">
                Controller API is unreachable
              </p>
              <p className="text-xs text-muted-foreground">
                Ensure the AI stack is running on{" "}
                <code className="font-mono">localhost:8080</code>. Showing
                cached or placeholder data.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* System stats */}
      <section className="space-y-3">
        <h2 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Runtime Metrics
        </h2>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard
            label="System Uptime"
            icon={Clock}
            value={
              status?.uptime_seconds != null
                ? formatUptime(status.uptime_seconds)
                : "—"
            }
          />
          <StatCard
            label="Total Requests"
            icon={Activity}
            value={
              metrics?.total_requests != null
                ? metrics.total_requests.toLocaleString()
                : "—"
            }
          />
          <StatCard
            label="Avg Latency"
            icon={Zap}
            value={
              metrics?.avg_latency_ms != null
                ? `${metrics.avg_latency_ms.toFixed(0)} ms`
                : "—"
            }
          />
          <StatCard
            label="Error Rate"
            icon={AlertTriangle}
            value={
              errorRate != null ? `${(errorRate * 100).toFixed(2)}%` : "—"
            }
            sub={errorRateWarn ? "Above 5% threshold" : undefined}
            warn={errorRateWarn}
          />
        </div>
      </section>

      {/* Version / release info row */}
      {status?.version && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Server className="size-3.5" />
          <span>
            BMT AI OS{" "}
            <span className="font-mono font-medium text-foreground">
              {status.version}
            </span>
          </span>
          {status.status && (
            <>
              <span className="text-border">·</span>
              <span className="capitalize">{status.status}</span>
            </>
          )}
        </div>
      )}

      {/* Services */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Services
          </h2>
          {!loading && status && (
            <span className="text-xs text-muted-foreground">
              {healthyCount} / {coreServices.length} healthy
            </span>
          )}
        </div>

        {loading && !status ? (
          /* Skeleton placeholders */
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <Card key={i} className="animate-pulse">
                <CardHeader>
                  <div className="h-4 w-24 rounded bg-muted" />
                </CardHeader>
                <CardContent>
                  <div className="h-3 w-16 rounded bg-muted" />
                </CardContent>
              </Card>
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {coreServices.map((svc) => (
              <ServiceCard key={svc.name} svc={svc} />
            ))}
          </div>
        )}
      </section>

      {/* Quick actions */}
      <section className="space-y-3">
        <h2 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Quick Actions
        </h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {QUICK_ACTIONS.map(({ href, label, icon: Icon, desc }) => (
            <Link key={href} href={href} className="group">
              <Card className="cursor-pointer transition-colors hover:bg-muted/50">
                <CardContent className="flex flex-col items-center gap-2 py-5 text-center">
                  <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary transition-colors group-hover:bg-primary/20">
                    <Icon className="size-4" />
                  </div>
                  <div>
                    <p className="text-sm font-medium">{label}</p>
                    <p className="text-xs text-muted-foreground">{desc}</p>
                  </div>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
