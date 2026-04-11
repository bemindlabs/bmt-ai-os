import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { BrainCog, Plus } from "lucide-react";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

export interface TrainingJob {
  id: string;
  model: string;
  dataset: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  progress: number;
  created_at: string;
  updated_at: string;
  current_loss?: number | null;
  tokens_per_sec?: number | null;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
}

interface TrainingJobsResponse {
  jobs: TrainingJob[];
  total: number;
  page: number;
  page_size: number;
}

async function fetchTrainingJobs(): Promise<TrainingJobsResponse | null> {
  try {
    const res = await fetch(`${BASE_URL}/api/v1/training/jobs`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return res.json() as Promise<TrainingJobsResponse>;
  } catch {
    return null;
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

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default async function TrainingPage() {
  const data = await fetchTrainingJobs();
  const jobs = data?.jobs ?? [];

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Training Jobs</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Manage on-device fine-tuning jobs (LoRA / QLoRA).
          </p>
        </div>
        <Button render={<a href="/training/new" />}>
          <Plus className="mr-2 size-4" />
          Start Training
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Jobs</CardTitle>
          <CardDescription>
            {data === null
              ? "Could not reach the training API."
              : jobs.length === 0
                ? "No training jobs found."
                : `${data.total} job${data.total !== 1 ? "s" : ""} total`}
          </CardDescription>
        </CardHeader>

        <CardContent className="p-0">
          {jobs.length === 0 ? (
            <div className="flex flex-col items-center gap-4 py-16 text-muted-foreground">
              <BrainCog className="size-12 opacity-30" />
              <p className="text-sm">
                {data === null
                  ? "Training API is unreachable. Check controller logs."
                  : "No jobs yet. Start a training run to fine-tune a model on this device."}
              </p>
              <Button variant="outline" render={<a href="/training/new" />}>
                <Plus className="mr-2 size-4" />
                Start Training
              </Button>
            </div>
          ) : (
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
                  <TableRow key={job.id}>
                    <TableCell className="font-mono text-xs">
                      {job.id}
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
                          <Progress value={job.progress} className="h-2" />
                          <p className="text-xs text-muted-foreground">
                            {job.progress.toFixed(1)}%
                            {job.current_loss != null &&
                              ` · loss ${job.current_loss.toFixed(4)}`}
                            {job.tokens_per_sec != null &&
                              ` · ${job.tokens_per_sec.toFixed(0)} tok/s`}
                          </p>
                        </div>
                      ) : job.status === "completed" ? (
                        <Progress value={100} className="h-2" />
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
