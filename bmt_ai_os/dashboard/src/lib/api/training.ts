import { apiFetch } from "./client";

export interface TrainingJob {
  id: string;
  model: string;
  dataset: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  progress: number;
  created_at: string;
  updated_at: string;
  config?: Record<string, unknown>;
  current_loss?: number | null;
  tokens_per_sec?: number | null;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  current_epoch?: number | null;
  epochs?: number | null;
  current_step?: number | null;
  total_steps?: number | null;
  learning_rate?: number | null;
  dataset_rows?: number | null;
  dataset_preview?: unknown[][] | null;
  dataset_headers?: string[] | null;
}

export interface TrainingJobListResponse {
  jobs: TrainingJob[];
  total: number;
  page: number;
  page_size: number;
}

export interface TrainingMetricPoint {
  step: number;
  loss: number;
  learning_rate?: number;
  epoch?: number;
  tokens_per_sec?: number;
}

export interface TrainingMetricsResponse {
  metrics: TrainingMetricPoint[];
}

export async function fetchTrainingJobs(
  page = 1,
  pageSize = 20,
): Promise<TrainingJobListResponse> {
  return apiFetch(`/api/v1/training/jobs?page=${page}&page_size=${pageSize}`);
}

export async function fetchTrainingJob(id: string): Promise<TrainingJob> {
  return apiFetch(`/api/v1/training/jobs/${id}`);
}

export async function createTrainingJob(req: {
  model: string;
  dataset: string;
  config?: Record<string, unknown>;
}): Promise<TrainingJob> {
  return apiFetch("/api/v1/training/jobs", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function cancelTrainingJob(id: string): Promise<{ status: string }> {
  return apiFetch(`/api/v1/training/jobs/${id}/cancel`, { method: "POST" });
}

export async function fetchTrainingMetrics(
  id: string,
): Promise<TrainingMetricsResponse> {
  return apiFetch(`/api/v1/training/jobs/${id}/metrics`);
}
