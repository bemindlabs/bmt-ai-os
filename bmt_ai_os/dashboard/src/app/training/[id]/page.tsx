"use client";

import { useEffect, useState, useCallback, use } from "react";
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
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TableHeader,
} from "@/components/ui/table";
import { LossChart } from "@/components/loss-chart";
import { TensorBoardEmbed } from "@/components/tensorboard-embed";
import {
  ArrowLeft,
  Clock,
  Cpu,
  Database,
  Layers,
  Loader2,
  CheckCircle2,
  XCircle,
  CircleDot,
  Ban,
} from "lucide-react";
import {
  fetchTrainingJob,
  fetchTrainingMetrics,
  cancelTrainingJob,
  type TrainingJob,
  type TrainingMetricPoint,
} from "@/lib/api";

// ---- Status badge -------------------------------------------------------

function StatusBadge({ status }: { status: TrainingJob["status"] }) {
  switch (status) {
    case "pending":
      return (
        <Badge variant="outline" className="gap-1.5">
          <Clock className="size-3 opacity-70" />
          Pending
        </Badge>
      );
    case "running":
      return (
        <Badge className="gap-1.5 bg-blue-600 text-white hover:bg-blue-600">
          <Loader2 className="size-3 animate-spin" />
          Running
        </Badge>
      );
    case "completed":
      return (
        <Badge className="gap-1.5 bg-green-600 text-white hover:bg-green-600">
          <CheckCircle2 className="size-3" />
          Completed
        </Badge>
      );
    case "failed":
      return (
        <Badge className="gap-1.5 bg-red-600 text-white hover:bg-red-600">
          <XCircle className="size-3" />
          Failed
        </Badge>
      );
    case "cancelled":
      return (
        <Badge variant="secondary" className="gap-1.5">
          <CircleDot className="size-3 opacity-70" />
          Cancelled
        </Badge>
      );
    default:
      return <Badge variant="outline">{status}</Badge>;
  }
}

// ---- Helpers ------------------------------------------------------------

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

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
  return `${h}h ${m % 60}m`;
}

const ACTIVE_STATUSES: TrainingJob["status"][] = ["running", "pending"];

// ---- Page ---------------------------------------------------------------

export default function TrainingJobPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);

  const [job, setJob] = useState<TrainingJob | null>(null);
  const [metrics, setMetrics] = useState<TrainingMetricPoint[]>([]);
  const [notFound, setNotFound] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [jobData, metricsData] = await Promise.all([
        fetchTrainingJob(id),
        fetchTrainingMetrics(id),
      ]);
      setJob(jobData);
      setMetrics(metricsData.metrics ?? []);
      setLoadError(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.includes("404")) {
        setNotFound(true);
      } else {
        setLoadError(msg);
      }
    }
  }, [id]);

  // Initial load
  useEffect(() => {
    load();
  }, [load]);

  // Auto-refresh every 5 s for active jobs
  useEffect(() => {
    if (!job) return;
    if (!ACTIVE_STATUSES.includes(job.status)) return;

    const interval = setInterval(load, 5_000);
    return () => clearInterval(interval);
  }, [job, load]);

  async function handleCancel() {
    if (!job) return;
    setCancelError(null);
    setCancelling(true);
    try {
      await cancelTrainingJob(id);
      await load();
    } catch (err) {
      setCancelError(
        err instanceof Error ? err.message : "Failed to cancel job",
      );
    } finally {
      setCancelling(false);
    }
  }

  // ---- Loading / error states -------------------------------------------

  if (notFound) {
    return (
      <div className="flex flex-col items-center gap-4 py-24 text-muted-foreground">
        <XCircle className="size-12 opacity-30" />
        <p className="text-sm">Training job not found.</p>
        <Link href="/training">
          <Button variant="outline" size="sm">
            <ArrowLeft className="size-4" />
            Back to Jobs
          </Button>
        </Link>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="flex flex-col items-center gap-4 py-24 text-muted-foreground">
        <XCircle className="size-12 opacity-30 text-red-500" />
        <p className="text-sm text-red-500">{loadError}</p>
        <Button variant="outline" size="sm" onClick={load}>
          Retry
        </Button>
      </div>
    );
  }

  if (!job) {
    return (
      <div className="space-y-6">
        {/* Skeleton header */}
        <div className="h-8 w-64 animate-pulse rounded-lg bg-muted" />
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-20 animate-pulse rounded-xl bg-muted" />
          ))}
        </div>
        <div className="h-64 animate-pulse rounded-xl bg-muted" />
      </div>
    );
  }

  // ---- Derived values ---------------------------------------------------

  const eta = estimateSecondsRemaining(job.progress, job.started_at);
  const lastMetric = metrics.length > 0 ? metrics[metrics.length - 1] : null;
  const isActive = ACTIVE_STATUSES.includes(job.status);

  return (
    <div className="space-y-6">
      {/* Header row */}
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <Link href="/training" aria-label="Back to training jobs">
              <Button variant="ghost" size="icon-sm">
                <ArrowLeft className="size-4" />
              </Button>
            </Link>
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

        {/* Cancel button — only for active jobs */}
        {isActive && (
          <div className="flex flex-col items-end gap-1">
            <Button
              variant="destructive"
              size="sm"
              onClick={handleCancel}
              disabled={cancelling}
            >
              {cancelling ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Ban className="size-4" />
              )}
              {cancelling ? "Cancelling…" : "Cancel Job"}
            </Button>
            {cancelError && (
              <p className="text-xs text-red-500">{cancelError}</p>
            )}
          </div>
        )}
      </div>

      {/* Progress bar — visible for running and completed */}
      {(job.status === "running" || job.status === "completed") && (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>
              {job.current_epoch != null && job.epochs != null
                ? `Epoch ${job.current_epoch} / ${job.epochs}`
                : "Progress"}
              {job.current_step != null && job.total_steps != null &&
                ` · Step ${job.current_step} / ${job.total_steps}`}
            </span>
            <span className="tabular-nums">{job.progress.toFixed(1)}%</span>
          </div>
          <Progress value={job.progress} className="h-2" />
        </div>
      )}

      {/* Error message for failed jobs */}
      {job.status === "failed" && job.error_message && (
        <div
          role="alert"
          className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive"
        >
          <span className="font-medium">Error: </span>
          {job.error_message}
        </div>
      )}

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
          <LossChart data={metrics} height={220} className="text-foreground" />
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
                {(
                  [
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
                  ] as { label: string; value: string }[]
                ).map(({ label, value }) => (
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
                        {(row as string[]).map((cell, ci) => (
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
        <CardContent className="px-4 pb-4">
          <TensorBoardEmbed url="http://localhost:6006" />
        </CardContent>
      </Card>
    </div>
  );
}
