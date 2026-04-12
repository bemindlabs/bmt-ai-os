"use client";

import { useState, useEffect, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  ArrowLeft,
  BrainCog,
  FolderOpen,
  Loader2,
} from "lucide-react";
import {
  fetchModels,
  createTrainingJob,
  type OllamaModel,
} from "@/lib/api";

// ---- Constants ----------------------------------------------------------

const FALLBACK_MODELS = [
  "qwen2.5-coder:1.5b",
  "qwen2.5-coder:3b",
  "qwen2.5-coder:7b",
  "qwen2.5:0.5b",
  "qwen2.5:1.5b",
];

const PRESETS = [
  {
    name: "LoRA",
    method: "lora",
    desc: "Low-Rank Adaptation — fast, memory-efficient",
    recommended: true,
  },
  {
    name: "QLoRA",
    method: "qlora",
    desc: "Quantized LoRA — fits in <4 GB VRAM",
    recommended: false,
  },
];

// ---- Field wrapper ------------------------------------------------------

function Field({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-xs font-medium">
        {label}
      </label>
      {children}
      {hint && (
        <p className="text-[11px] text-muted-foreground">{hint}</p>
      )}
    </div>
  );
}

// ---- Page ---------------------------------------------------------------

export default function NewTrainingPage() {
  const router = useRouter();

  // Model list
  const [models, setModels] = useState<OllamaModel[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);

  // Form fields
  const [baseModel, setBaseModel] = useState(FALLBACK_MODELS[0]);
  const [dataset, setDataset] = useState("");
  const [method, setMethod] = useState("lora");
  const [epochs, setEpochs] = useState("3");
  const [learningRate, setLearningRate] = useState("2e-4");
  const [batchSize, setBatchSize] = useState("4");
  const [loraRank, setLoraRank] = useState("16");

  // Submit state
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch available models from the API
  useEffect(() => {
    fetchModels()
      .then((res) => {
        if (res.models.length > 0) {
          setModels(res.models);
          setBaseModel(res.models[0].name);
        }
      })
      .catch(() => {
        // Fall back to static list; leave baseModel as default
      })
      .finally(() => setModelsLoading(false));
  }, []);

  const modelNames =
    models.length > 0 ? models.map((m) => m.name) : FALLBACK_MODELS;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      const job = await createTrainingJob({
        model: baseModel,
        dataset,
        config: {
          method,
          epochs: parseInt(epochs, 10),
          learning_rate: parseFloat(learningRate),
          batch_size: parseInt(batchSize, 10),
          lora_rank: parseInt(loraRank, 10),
        },
      });
      router.push(`/training/${job.id}`);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to start training job",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link href="/training">
          <Button variant="ghost" size="icon-sm" aria-label="Back to training jobs">
            <ArrowLeft className="size-4" />
          </Button>
        </Link>
        <div>
          <h1 className="text-xl font-semibold">New Training Job</h1>
          <p className="text-sm text-muted-foreground">
            Fine-tune a model with LoRA / QLoRA on this device
          </p>
        </div>
      </div>

      <form onSubmit={handleSubmit}>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <BrainCog className="size-5" />
              Training Configuration
            </CardTitle>
            <CardDescription>
              Configure fine-tuning parameters for your training run
            </CardDescription>
          </CardHeader>

          <CardContent className="flex flex-col gap-5">
            {/* Error banner */}
            {error && (
              <div
                role="alert"
                className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2.5 text-xs text-destructive"
              >
                {error}
              </div>
            )}

            {/* Base model */}
            <Field
              label="Base Model"
              htmlFor="model"
              hint={
                modelsLoading
                  ? "Loading models from Ollama…"
                  : models.length === 0
                    ? "Ollama not reachable — showing common models"
                    : undefined
              }
            >
              <select
                id="model"
                value={baseModel}
                onChange={(e) => setBaseModel(e.target.value)}
                className="h-9 rounded-lg border border-input bg-background px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                {modelNames.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </Field>

            {/* Dataset path */}
            <Field
              label="Dataset Path"
              htmlFor="dataset"
              hint="Path to a JSONL file with instruction-tuning examples"
            >
              <div className="flex gap-2">
                <Input
                  id="dataset"
                  required
                  placeholder="/data/datasets/my-dataset.jsonl"
                  value={dataset}
                  onChange={(e) => setDataset(e.target.value)}
                  className="h-9"
                />
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  aria-label="Browse dataset files"
                  onClick={() => {
                    // Opens file browser page; populate field via URL param if implemented
                    const picked = window.prompt(
                      "Enter dataset path:",
                      dataset,
                    );
                    if (picked !== null) setDataset(picked);
                  }}
                  title="Browse files"
                >
                  <FolderOpen className="size-4" />
                </Button>
              </div>
            </Field>

            {/* Method selector */}
            <div className="flex flex-col gap-2">
              <span className="text-xs font-medium">Method</span>
              <div className="flex gap-3">
                {PRESETS.map((p) => (
                  <button
                    key={p.method}
                    type="button"
                    onClick={() => setMethod(p.method)}
                    className={`flex-1 rounded-lg border p-3 text-left transition-colors ${
                      method === p.method
                        ? "border-primary bg-primary/5"
                        : "border-border hover:border-primary/30"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">{p.name}</span>
                      {p.recommended && (
                        <Badge variant="secondary" className="text-[10px]">
                          recommended
                        </Badge>
                      )}
                      {method === p.method && !p.recommended && (
                        <Badge variant="secondary" className="text-[10px]">
                          selected
                        </Badge>
                      )}
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {p.desc}
                    </p>
                  </button>
                ))}
              </div>
            </div>

            {/* Hyperparameters — 2 x 2 grid */}
            <div className="grid grid-cols-2 gap-4">
              <Field label="Epochs" htmlFor="epochs">
                <Input
                  id="epochs"
                  type="number"
                  min="1"
                  max="100"
                  value={epochs}
                  onChange={(e) => setEpochs(e.target.value)}
                  className="h-9"
                />
              </Field>

              <Field label="Learning Rate" htmlFor="lr">
                <Input
                  id="lr"
                  value={learningRate}
                  placeholder="2e-4"
                  onChange={(e) => setLearningRate(e.target.value)}
                  className="h-9"
                />
              </Field>

              <Field label="Batch Size" htmlFor="batch-size">
                <Input
                  id="batch-size"
                  type="number"
                  min="1"
                  max="256"
                  value={batchSize}
                  onChange={(e) => setBatchSize(e.target.value)}
                  className="h-9"
                />
              </Field>

              <Field
                label="LoRA Rank"
                htmlFor="lora-rank"
                hint="Higher = more capacity, more VRAM"
              >
                <Input
                  id="lora-rank"
                  type="number"
                  min="1"
                  max="256"
                  value={loraRank}
                  onChange={(e) => setLoraRank(e.target.value)}
                  className="h-9"
                />
              </Field>
            </div>
          </CardContent>

          <CardFooter className="flex justify-between">
            <Link href="/training">
              <Button type="button" variant="outline">
                Cancel
              </Button>
            </Link>
            <Button type="submit" disabled={submitting || !dataset.trim()}>
              {submitting ? (
                <>
                  <Loader2 className="size-4 animate-spin" />
                  Starting…
                </>
              ) : (
                "Start Training"
              )}
            </Button>
          </CardFooter>
        </Card>
      </form>
    </div>
  );
}
