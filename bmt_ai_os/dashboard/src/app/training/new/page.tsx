"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
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
import { ArrowLeft, BrainCog } from "lucide-react";

const PRESETS = [
  { name: "LoRA (recommended)", method: "lora", desc: "Low-Rank Adaptation — fast, memory-efficient" },
  { name: "QLoRA", method: "qlora", desc: "Quantized LoRA — fits in <4GB VRAM" },
];

const MODELS = [
  "qwen2.5-coder:1.5b",
  "qwen2.5-coder:3b",
  "qwen2.5-coder:7b",
  "qwen2.5:0.5b",
  "qwen2.5:1.5b",
];

export default function NewTrainingPage() {
  const router = useRouter();
  const [baseModel, setBaseModel] = useState(MODELS[0]);
  const [dataset, setDataset] = useState("");
  const [method, setMethod] = useState("lora");
  const [epochs, setEpochs] = useState("3");
  const [learningRate, setLearningRate] = useState("2e-4");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const res = await fetch("/api/v1/training/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_model: baseModel,
          dataset_path: dataset,
          method,
          epochs: parseInt(epochs, 10),
          learning_rate: parseFloat(learningRate),
        }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `${res.status}: ${res.statusText}`);
      }

      router.push("/training");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start training");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div className="flex items-center gap-3">
        <a href="/training">
          <Button variant="ghost" size="icon">
            <ArrowLeft className="size-4" />
          </Button>
        </a>
        <div>
          <h1 className="text-xl font-semibold">Start Training Job</h1>
          <p className="text-sm text-muted-foreground">
            Fine-tune a model with LoRA/QLoRA on this device
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
              Configure the fine-tuning parameters for your training run
            </CardDescription>
          </CardHeader>

          <CardContent className="flex flex-col gap-5">
            {error && (
              <div
                role="alert"
                className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2.5 text-xs text-destructive"
              >
                {error}
              </div>
            )}

            <div className="flex flex-col gap-1.5">
              <label htmlFor="model" className="text-xs font-medium">
                Base Model
              </label>
              <select
                id="model"
                value={baseModel}
                onChange={(e) => setBaseModel(e.target.value)}
                className="h-10 rounded-lg border border-input bg-background px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                {MODELS.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>

            <div className="flex flex-col gap-1.5">
              <label htmlFor="dataset" className="text-xs font-medium">
                Dataset Path
              </label>
              <Input
                id="dataset"
                required
                placeholder="/data/datasets/my-dataset.jsonl"
                value={dataset}
                onChange={(e) => setDataset(e.target.value)}
                className="h-10"
              />
              <p className="text-[11px] text-muted-foreground">
                Path to a JSONL file with instruction-tuning examples
              </p>
            </div>

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
                      {method === p.method && (
                        <Badge variant="secondary" className="text-[10px]">
                          Selected
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

            <div className="grid grid-cols-2 gap-4">
              <div className="flex flex-col gap-1.5">
                <label htmlFor="epochs" className="text-xs font-medium">
                  Epochs
                </label>
                <Input
                  id="epochs"
                  type="number"
                  min="1"
                  max="100"
                  value={epochs}
                  onChange={(e) => setEpochs(e.target.value)}
                  className="h-10"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="lr" className="text-xs font-medium">
                  Learning Rate
                </label>
                <Input
                  id="lr"
                  value={learningRate}
                  onChange={(e) => setLearningRate(e.target.value)}
                  className="h-10"
                />
              </div>
            </div>
          </CardContent>

          <CardFooter className="flex justify-between">
            <a href="/training">
              <Button type="button" variant="outline">
                Cancel
              </Button>
            </a>
            <Button type="submit" disabled={loading || !dataset}>
              {loading ? (
                <span className="flex items-center gap-2">
                  <span className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                  Starting...
                </span>
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
