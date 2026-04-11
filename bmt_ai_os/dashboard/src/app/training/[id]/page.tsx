import { notFound } from "next/navigation";
import Link from "next/link";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
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
import { LossChart } from "@/components/loss-chart";
import { TensorBoardEmbed } from "@/components/tensorboard-embed";
import { ArrowLeft, Clock, Cpu, Database, Layers } from "lucide-react";
import type {
  TrainingJob,
  TrainingMetricPoint,
  TrainingMetricsResponse,
} from "@/lib/api";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

async function getJob(id: string): Promise<TrainingJob | null> {
  try {
    const res = await fetch(`${BASE_URL}/api/v1/training/jobs/${id}`, {
      cache: "no-store",
    });
    if (res.status === 404) return null;
    if (!res.ok) return null;
    return res.json() as Promise<TrainingJob>;
  } catch {
    return null;
  }
}

async function getMetrics(id: string): Promise<TrainingMetricPoint[]> {
  try {
    const res = await fetch(`${BASE_URL}/api/v1/training/jobs/${id}/metrics`, {
      cache: "no-store",
    });
    if (!res.ok) return [];
    const data = (await res.json()) as TrainingMetricsResponse;
    return data.metrics ?? [];
  } catch {
    return [];
  }
}

function StatusBadge({ status }: { status: TrainingJob["status"] }) {
  switch (status) {
    case "pending":
      return <Badge variant="outline">Pending</Badge>;
    case "running":
      return (
        <Badge className="animate-pulse bg-blue-600 text-white hover:bg-blue-600">
          Running
        </Badge>
      );
    case "completed":
      return (
        <Badge className="bg-green-600 text-white hover:bg-green-600">
          Completed
        </Badge>
      );
    case "failed":
      return (
        <Badge className="bg-red-600 text-white hover:bg-red-600">
          Failed
        </Badge>
      );
    case "cancelled":
      return <Badge variant="secondary">Cancelled</Badge>;
    default:
      return <Badge variant="outline">{status}</Badge>;
  }
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

/**
 * Estimate seconds remaining given current progress (0-100) and elapsed seconds.
 * Returns null when there is not enough data.
 */
function estimateSecondsRemaining(
  progress: number,
  startedAt: string | null | undefined,
): number | null {
  if (!startedAt || progress <= 0 || progress >= 100) return null;
  const elapsed = (Date.now() - new Date(startedAt).getTime()) / 1000;
  if (elapsed <= 0) return null;
  const total = elapsed / (progress / 100);
  return Math.max(0, Math.round(total - elapsed));
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m < 60) return `${m}m ${s}s`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return `${h}h ${rm}m`;
}

export default async function TrainingJobPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const [jobOrNull, metrics] = await Promise.all([getJob(id), getMetrics(id)]);

  if (!jobOrNull) notFound();

  // notFound() throws — TypeScript does not narrow through it, so we assert here.
  // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
  const job: TrainingJob = jobOrNull!;

  const eta = estimateSecondsRemaining(job.progress, job.started_at);
  const lastMetric = metrics.length > 0 ? metrics[metrics.length - 1] : null;

  return (
    <div className="space-y-6">
      {/* Back link + header */}
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="icon-sm" asChild>
              <Link href="/training" aria-label="Back to training jobs">
                <ArrowLeft className="size-4" />
              </Link>
            </Button>
            <h1 className="text-xl font-semibold">
              Job{" "}
              <span className="font-mono text-base text-muted-foreground">
                {job.id}
              </span>
            </h1>
            <StatusBadge status={job.status} />
          </div>
          <p className="pl-9 text-sm text-muted-foreground">
            {job.model} &mdash; fine-tuned on{" "}
            <span className="font-mono">{job.dataset}</span>
          </p>
        </div>
      </div>

      {/* Key metrics row */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Card size="sm">
          <CardHeader>
            <CardDescription className="flex items-center gap-1.5">
              <Layers className="size-3.5 opacity-60" />
              Progress
            </CardDescription>
            <CardTitle className="text-2xl tabular-nums">
              {job.progress.toFixed(1)}%
            </CardTitle>
          </CardHeader>
        </Card>

        <Card size="sm">
          <CardHeader>
            <CardDescription className="flex items-center gap-1.5">
              <Cpu className="size-3.5 opacity-60" />
              Loss
            </CardDescription>
            <CardTitle className="text-2xl tabular-nums">
              {job.current_loss != null
                ? job.current_loss.toFixed(4)
                : lastMetric
                  ? lastMetric.loss.toFixed(4)
                  : "—"}
            </CardTitle>
          </CardHeader>
        </Card>

        <Card size="sm">
          <CardHeader>
            <CardDescription className="flex items-center gap-1.5">
              <Database className="size-3.5 opacity-60" />
              Throughput
            </CardDescription>
            <CardTitle className="text-2xl tabular-nums">
              {job.tokens_per_sec != null
                ? `${job.tokens_per_sec.toFixed(0)} tok/s`
                : lastMetric?.tokens_per_sec != null
                  ? `${lastMetric.tokens_per_sec.toFixed(0)} tok/s`
                  : "—"}
            </CardTitle>
          </CardHeader>
        </Card>

        <Card size="sm">
          <CardHeader>
            <CardDescription className="flex items-center gap-1.5">
              <Clock className="size-3.5 opacity-60" />
              ETA
            </CardDescription>
            <CardTitle className="text-2xl tabular-nums">
              {job.status === "running" && eta != null
                ? formatDuration(eta)
                : job.status === "completed"
                  ? "Done"
                  : "—"}
            </CardTitle>
          </CardHeader>
        </Card>
      </div>

      {/* Loss chart */}
      <Card>
        <CardHeader>
          <CardTitle>Training Loss</CardTitle>
          <CardDescription>
            Loss per step
            {metrics.length > 0 &&
              ` · ${metrics.length} data point${metrics.length !== 1 ? "s" : ""}`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <LossChart
            data={metrics}
            height={220}
            className="text-foreground"
          />
        </CardContent>
      </Card>

      {/* Job details + dataset preview */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Job details */}
        <Card>
          <CardHeader>
            <CardTitle>Job Details</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableBody>
                {[
                  { label: "ID", value: job.id },
                  { label: "Model", value: job.model },
                  { label: "Dataset", value: job.dataset },
                  {
                    label: "Epoch",
                    value:
                      job.current_epoch != null && job.epochs != null
                        ? `${job.current_epoch} / ${job.epochs}`
                        : "—",
                  },
                  {
                    label: "Step",
                    value:
                      job.current_step != null && job.total_steps != null
                        ? `${job.current_step} / ${job.total_steps}`
                        : "—",
                  },
                  {
                    label: "Learning Rate",
                    value:
                      job.learning_rate != null
                        ? job.learning_rate.toExponential(2)
                        : lastMetric?.learning_rate != null
                          ? lastMetric.learning_rate.toExponential(2)
                          : "—",
                  },
                  { label: "Created", value: formatDate(job.created_at) },
                  { label: "Started", value: formatDate(job.started_at) },
                  { label: "Finished", value: formatDate(job.completed_at) },
                  ...(job.error_message
                    ? [{ label: "Error", value: job.error_message }]
                    : []),
                ].map(({ label, value }) => (
                  <TableRow key={label}>
                    <TableHead className="w-32 py-2 text-xs font-medium">
                      {label}
                    </TableHead>
                    <TableCell className="py-2 font-mono text-xs text-muted-foreground">
                      {value}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        {/* Dataset preview */}
        <Card>
          <CardHeader>
            <CardTitle>Dataset Preview</CardTitle>
            <CardDescription>
              {job.dataset_rows != null
                ? `${job.dataset_rows.toLocaleString()} rows total`
                : "First 5 rows"}
            </CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            {job.dataset_preview && job.dataset_preview.length > 0 ? (
              <div className="overflow-x-auto">
                <Table>
                  {job.dataset_headers && job.dataset_headers.length > 0 && (
                    <TableHeader>
                      <TableRow>
                        {job.dataset_headers.map((h) => (
                          <TableHead key={h} className="text-xs">
                            {h}
                          </TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                  )}
                  <TableBody>
                    {job.dataset_preview.slice(0, 5).map((row, ri) => (
                      <TableRow key={ri}>
                        {row.map((cell, ci) => (
                          <TableCell
                            key={ci}
                            className="max-w-[200px] truncate font-mono text-xs text-muted-foreground"
                            title={cell}
                          >
                            {cell}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <div className="flex items-center justify-center py-12 text-xs text-muted-foreground">
                Dataset preview not available for this job.
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* TensorBoard embed */}
      <Card>
        <CardHeader>
          <CardTitle>TensorBoard</CardTitle>
          <CardDescription>
            Live training graphs from TensorBoard on{" "}
            <code className="font-mono text-xs">localhost:6006</code>
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0 pb-4 px-4">
          <TensorBoardEmbed url="http://localhost:6006" />
        </CardContent>
      </Card>
    </div>
  );
}
