"use client";

import { useState } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";

const AVAILABLE_MODELS = [
  { name: "qwen2.5-coder:7b", size: "4.7 GB", desc: "Coding (recommended)" },
  { name: "qwen2.5-coder:3b", size: "1.9 GB", desc: "Coding (light)" },
  { name: "qwen2.5-coder:1.5b", size: "986 MB", desc: "Coding (minimal)" },
  { name: "qwen2.5:7b", size: "4.7 GB", desc: "General purpose" },
  { name: "qwen2.5:3b", size: "1.9 GB", desc: "General (light)" },
  { name: "qwen2.5:0.5b", size: "397 MB", desc: "General (tiny)" },
  { name: "llama3.2:3b", size: "2.0 GB", desc: "Meta Llama 3.2" },
  { name: "llama3.2:1b", size: "1.3 GB", desc: "Meta Llama 3.2 (small)" },
  { name: "gemma4:12b", size: "7.6 GB", desc: "Google Gemma 4" },
  { name: "gemma4:4b", size: "2.5 GB", desc: "Google Gemma 4 (small)" },
  { name: "gemma2:2b", size: "1.6 GB", desc: "Google Gemma 2" },
  { name: "phi3.5:3.8b", size: "2.2 GB", desc: "Microsoft Phi-3.5" },
  { name: "mistral:7b", size: "4.1 GB", desc: "Mistral 7B" },
  { name: "codellama:7b", size: "3.8 GB", desc: "Meta Code Llama" },
  { name: "deepseek-coder-v2:16b", size: "8.9 GB", desc: "DeepSeek Coder V2" },
  { name: "nomic-embed-text", size: "274 MB", desc: "Embeddings" },
];

interface PullModelFormProps {
  installedModels?: string[];
}

export function PullModelForm({ installedModels = [] }: PullModelFormProps) {
  const [selectedModel, setSelectedModel] = useState("");
  const [customModel, setCustomModel] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [message, setMessage] = useState("");

  const modelToPull = customModel.trim() || selectedModel;
  const installed = new Set(installedModels.map((m) => m.split(":")[0]));

  async function handlePull() {
    if (!modelToPull) return;

    setStatus("loading");
    setMessage("");

    try {
      const res = await fetch("/api/pull", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: modelToPull }),
      });

      if (!res.ok) {
        throw new Error(`Server responded with ${res.status}`);
      }

      setStatus("success");
      setMessage(`Pull request accepted for "${modelToPull}".`);
      setSelectedModel("");
      setCustomModel("");
    } catch (err) {
      setStatus("error");
      setMessage(
        err instanceof Error ? err.message : "Unknown error occurred."
      );
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Pull New Model</CardTitle>
        <CardDescription>
          Select from popular models or enter a custom Ollama model name.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Available models grid */}
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {AVAILABLE_MODELS.map((m) => {
            const isInstalled = installed.has(m.name.split(":")[0]);
            const isSelected = selectedModel === m.name && !customModel.trim();
            return (
              <button
                key={m.name}
                type="button"
                disabled={status === "loading"}
                onClick={() => {
                  setSelectedModel(m.name);
                  setCustomModel("");
                }}
                className={`flex flex-col items-start rounded-lg border px-3 py-2 text-left text-sm transition-colors disabled:opacity-50 ${
                  isSelected
                    ? "border-primary bg-primary/10"
                    : "border-input hover:border-primary/50 hover:bg-muted/50"
                }`}
              >
                <div className="flex w-full items-center justify-between">
                  <span className="font-mono text-xs font-medium">{m.name}</span>
                  {isInstalled && (
                    <span className="text-[10px] text-green-500">installed</span>
                  )}
                </div>
                <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
                  <span>{m.desc}</span>
                  <span className="text-[10px]">{m.size}</span>
                </div>
              </button>
            );
          })}
        </div>

        {/* Custom model input */}
        <div className="flex items-start gap-3">
          <input
            type="text"
            value={customModel}
            onChange={(e) => setCustomModel(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                handlePull();
              }
            }}
            placeholder="Or enter a custom model name…"
            className="h-8 flex-1 rounded-lg border border-input bg-background px-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring/50"
            disabled={status === "loading"}
          />
          <Button
            onClick={handlePull}
            disabled={status === "loading" || !modelToPull}
          >
            {status === "loading" ? "Pulling…" : "Pull"}
          </Button>
        </div>

        {message && (
          <p
            className={`text-sm ${
              status === "error" ? "text-destructive" : "text-muted-foreground"
            }`}
          >
            {message}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
