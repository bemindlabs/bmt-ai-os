import { fetchStatus, fetchMetrics, formatUptime } from "@/lib/api";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

function ServiceHealthCard({
  name,
  status,
}: {
  name: string;
  status: string;
}) {
  const healthy = status === "healthy";
  const degraded = status === "degraded";

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>{name}</CardTitle>
          <Badge
            variant={healthy ? "default" : degraded ? "outline" : "destructive"}
          >
            {status}
          </Badge>
        </div>
        <CardDescription>Service status</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex items-center gap-2">
          <span
            className={`size-2.5 rounded-full ${
              healthy
                ? "bg-green-500"
                : degraded
                  ? "bg-yellow-500"
                  : "bg-red-500"
            }`}
          />
          <span className="text-xs text-muted-foreground capitalize">
            {status}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

function StatCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardDescription>{label}</CardDescription>
        <CardTitle className="text-2xl tabular-nums">{value}</CardTitle>
      </CardHeader>
      {sub && (
        <CardContent>
          <p className="text-xs text-muted-foreground">{sub}</p>
        </CardContent>
      )}
    </Card>
  );
}

export default async function OverviewPage() {
  // Fetch status and metrics in parallel; degrade gracefully on error.
  const [statusResult, metricsResult] = await Promise.allSettled([
    fetchStatus(),
    fetchMetrics(),
  ]);

  const status =
    statusResult.status === "fulfilled" ? statusResult.value : null;
  const metrics =
    metricsResult.status === "fulfilled" ? metricsResult.value : null;

  // Expected core services — fall back if API is unreachable
  const coreServices = status?.services ?? [
    { name: "Ollama", status: "unknown" },
    { name: "ChromaDB", status: "unknown" },
    { name: "Controller", status: "unknown" },
  ];

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold">System Overview</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Live status of AI stack services and runtime metrics.
        </p>
      </div>

      {/* Service health */}
      <section className="space-y-3">
        <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
          Services
        </h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {coreServices.map((svc) => (
            <ServiceHealthCard
              key={svc.name}
              name={svc.name}
              status={svc.status}
            />
          ))}
        </div>
      </section>

      {/* Quick stats */}
      <section className="space-y-3">
        <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
          Runtime Metrics
        </h2>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard
            label="Uptime"
            value={status ? formatUptime(status.uptime) : "—"}
          />
          <StatCard
            label="Total Requests"
            value={
              metrics
                ? metrics.total_requests.toLocaleString()
                : "—"
            }
          />
          <StatCard
            label="Avg Latency"
            value={
              metrics
                ? `${metrics.avg_latency_ms.toFixed(0)} ms`
                : "—"
            }
          />
          <StatCard
            label="Error Rate"
            value={
              metrics
                ? `${(metrics.error_rate * 100).toFixed(2)}%`
                : "—"
            }
            sub={
              metrics && metrics.error_rate > 0.05
                ? "Above threshold"
                : undefined
            }
          />
        </div>
      </section>

      {/* API unreachable notice */}
      {!status && (
        <Card>
          <CardContent className="pt-4">
            <p className="text-sm text-muted-foreground">
              Controller API is unreachable. Ensure the AI stack is running on{" "}
              <code className="font-mono text-xs">localhost:8080</code>.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
