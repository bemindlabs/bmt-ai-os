"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
  BrainCog,
  Plus,
  Loader2,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Clock,
  CircleDot,
} from "lucide-react";
import {
  fetchTrainingJobs,
  type TrainingJob,
  type TrainingJobListResponse,
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

// ---- Skeleton row -------------------------------------------------------

function SkeletonRow() {
  return (
    <TableRow>
      {Array.from({ length: 6 }).map((_, i) => (
        <TableCell key={i}>
          <div className="h-4 animate-pulse rounded bg-muted" />
        </TableCell>
      ))}
    </TableRow>
  );
}

// ---- Helpers ------------------------------------------------------------

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function hasActiveJobs(jobs: TrainingJob[]): boolean {
  return jobs.some((j) => j.status === "running" || j.status === "pending");
}

// ---- Page ---------------------------------------------------------------

export default function TrainingPage() {
  const [data, setData] = useState<TrainingJobListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const result = await fetchTrainingJobs();
      setData(result);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load jobs");
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    load();
  }, [load]);

  // Auto-refresh every 10 s while active jobs exist
  useEffect(() => {
    if (!data) return;
    if (!hasActiveJobs(data.jobs)) return;

    const id = setInterval(load, 10_000);
    return () => clearInterval(id);
  }, [data, load]);

  const jobs = data?.jobs ?? [];
  const isFirstLoad = loading && data === null;

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Training Jobs</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Manage on-device fine-tuning jobs (LoRA / QLoRA).
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={load}
            disabled={loading}
            aria-label="Refresh jobs"
          >
            <RefreshCw className={cn("size-4", loading && "animate-spin")} />
          </Button>
          <Link href="/training/new" className={cn(buttonVariants())}>
            <Plus className="size-4" />
            New Job
          </Link>
        </div>
      </div>

      {/* Table card */}
      <Card>
        <CardHeader>
          <CardTitle>Jobs</CardTitle>
          <CardDescription>
            {error
              ? "Could not reach the training API."
              : isFirstLoad
                ? "Loading…"
                : jobs.length === 0
                  ? "No training jobs found."
                  : `${data!.total} job${data!.total !== 1 ? "s" : ""} total`}
          </CardDescription>
        </CardHeader>

        <CardContent className="p-0">
          {/* Error banner */}
          {error && (
            <p className="px-6 py-4 text-sm text-red-500">{error}</p>
          )}

          {/* Empty state */}
          {!error && !isFirstLoad && jobs.length === 0 && (
            <div className="flex flex-col items-center gap-4 py-16 text-muted-foreground">
              <BrainCog className="size-12 opacity-30" />
              <p className="text-sm">
                No jobs yet. Start a training run to fine-tune a model on this
                device.
              </p>
              <Link
                href="/training/new"
                className={cn(buttonVariants({ variant: "outline" }))}
              >
                <Plus className="size-4" />
                New Job
              </Link>
            </div>
          )}

          {/* Skeleton while loading first page */}
          {isFirstLoad && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ID</TableHead>
                  <TableHead>Model</TableHead>
                  <TableHead>Dataset</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Progress</TableHead>
                  <TableHead>Created</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {Array.from({ length: 4 }).map((_, i) => (
                  <SkeletonRow key={i} />
                ))}
              </TableBody>
            </Table>
          )}

          {/* Populated table */}
          {!isFirstLoad && jobs.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ID</TableHead>
                  <TableHead>Model</TableHead>
                  <TableHead>Dataset</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Progress</TableHead>
                  <TableHead>Created</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {jobs.map((job) => (
                  <TableRow
                    key={job.id}
                    className="cursor-pointer hover:bg-muted/50"
                    onClick={() =>
                      (window.location.href = `/training/${job.id}`)
                    }
                  >
                    <TableCell className="font-mono text-xs">
                      {job.id.slice(0, 8)}&hellip;
                    </TableCell>
                    <TableCell className="font-medium">{job.model}</TableCell>
                    <TableCell className="max-w-[180px] truncate text-sm text-muted-foreground">
                      {job.dataset}
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={job.status} />
                    </TableCell>
                    <TableCell className="min-w-[140px]">
                      {job.status === "running" ? (
                        <div className="space-y-1">
                          <Progress value={job.progress} className="h-1.5" />
                          <p className="text-xs text-muted-foreground">
                            {job.progress.toFixed(1)}%
                            {job.current_loss != null &&
                              ` · loss ${job.current_loss.toFixed(4)}`}
                            {job.tokens_per_sec != null &&
                              ` · ${job.tokens_per_sec.toFixed(0)} tok/s`}
                          </p>
                        </div>
                      ) : job.status === "completed" ? (
                        <Progress value={100} className="h-1.5" />
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDate(job.created_at)}
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
