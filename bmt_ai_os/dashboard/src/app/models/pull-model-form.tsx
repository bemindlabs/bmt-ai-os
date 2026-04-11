"use client";

import { useState, useRef } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Download, X, CheckCircle, AlertCircle } from "lucide-react";

const AVAILABLE_MODELS = [
  { name: "qwen2.5-coder:7b", size: "4.7 GB", desc: "Coding (recommended)" },
  { name: "qwen2.5-coder:3b", size: "1.9 GB", desc: "Coding (light)" },
  { name: "qwen2.5-coder:1.5b", size: "986 MB", desc: "Coding (minimal)" },
  { name: "qwen2.5:7b", size: "4.7 GB", desc: "General purpose" },
  { name: "qwen2.5:3b", size: "1.9 GB", desc: "General (light)" },
  { name: "qwen2.5:0.5b", size: "397 MB", desc: "General (tiny)" },
  { name: "llama3.2:3b", size: "2.0 GB", desc: "Meta Llama 3.2" },
  { name: "gemma3:4b", size: "2.5 GB", desc: "Google Gemma 3 (small)" },
  { name: "gemma3:1b", size: "815 MB", desc: "Google Gemma 3 (tiny)" },
  { name: "phi3.5:3.8b", size: "2.2 GB", desc: "Microsoft Phi-3.5" },
  { name: "mistral:7b", size: "4.1 GB", desc: "Mistral 7B" },
  { name: "nomic-embed-text", size: "274 MB", desc: "Embeddings" },
];

interface PullModelFormProps {
  installedModels?: string[];
}

function fmtBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

export function PullModelForm({ installedModels = [] }: PullModelFormProps) {
  const [selectedModel, setSelectedModel] = useState("");
  const [customModel, setCustomModel] = useState("");
  const [status, setStatus] = useState<"idle" | "pulling" | "success" | "error">("idle");
  const [message, setMessage] = useState("");
  const [pullStatus, setPullStatus] = useState("");
  const [progress, setProgress] = useState(0);
  const [totalSize, setTotalSize] = useState(0);
  const [completedSize, setCompletedSize] = useState(0);
  const abortRef = useRef<AbortController | null>(null);

  const modelToPull = customModel.trim() || selectedModel;
  const installed = new Set(installedModels);

  async function handlePull() {
    if (!modelToPull) return;
    setStatus("pulling");
    setMessage("");
    setPullStatus("Connecting to Ollama...");
    setProgress(0);
    setTotalSize(0);
    setCompletedSize(0);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch("/api/pull", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: modelToPull }),
        signal: controller.signal,
      });
      if (!res.ok) throw new Error(`Server responded with ${res.status}`);
      if (!res.body) throw new Error("No response body");

      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
      let finalStatus: "success" | "error" = "success";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        for (const line of value.split("\n")) {
          if (!line.trim()) continue;
          try {
            const data = JSON.parse(line);
            if (data.error) { finalStatus = "error"; setMessage(data.error); break; }
            if (data.status) setPullStatus(data.status);
            if (data.total && data.completed) {
              setTotalSize(data.total);
              setCompletedSize(data.completed);
              setProgress(Math.round((data.completed / data.total) * 100));
            }
            if (data.status === "success") { finalStatus = "success"; setProgress(100); }
          } catch { /* skip non-JSON lines */ }
        }
      }

      setStatus(finalStatus);
      if (finalStatus === "success" && !message) setMessage(`Successfully pulled "${modelToPull}"`);
    } catch (err) {
      if ((err as Error).name === "AbortError") { setStatus("idle"); setMessage("Pull cancelled."); return; }
      setStatus("error");
      setMessage(err instanceof Error ? err.message : "Unknown error");
    } finally { abortRef.current = null; }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Pull New Model</CardTitle>
        <CardDescription>Select a model or enter a custom name. Progress streams in real-time.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {AVAILABLE_MODELS.map((m) => {
            const isInstalled = installed.has(m.name);
            const isSelected = selectedModel === m.name && !customModel.trim();
            return (
              <button key={m.name} type="button" disabled={status === "pulling"}
                onClick={() => { setSelectedModel(m.name); setCustomModel(""); }}
                className={`flex flex-col items-start rounded-lg border px-3 py-2 text-left text-sm transition-colors disabled:opacity-50 ${isSelected ? "border-primary bg-primary/10" : "border-input hover:border-primary/50 hover:bg-muted/50"}`}>
                <div className="flex w-full items-center justify-between">
                  <span className="font-mono text-xs font-medium">{m.name}</span>
                  {isInstalled && <span className="text-[10px] text-green-500">installed</span>}
                </div>
                <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
                  <span>{m.desc}</span>
                  <span className="text-[10px]">{m.size}</span>
                </div>
              </button>
            );
          })}
        </div>

        <div className="flex items-start gap-3">
          <input type="text" value={customModel} onChange={(e) => setCustomModel(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); handlePull(); } }}
            placeholder="Or enter a custom model name..."
            className="h-8 flex-1 rounded-lg border border-input bg-background px-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring/50"
            disabled={status === "pulling"} />
          {status === "pulling" ? (
            <Button variant="destructive" onClick={() => abortRef.current?.abort()}>
              <X className="mr-1.5 size-3.5" />Cancel
            </Button>
          ) : (
            <Button onClick={handlePull} disabled={!modelToPull}>
              <Download className="mr-1.5 size-3.5" />Pull
            </Button>
          )}
        </div>

        {status === "pulling" && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">{pullStatus}</span>
              <span className="font-mono text-muted-foreground">
                {totalSize > 0 ? `${fmtBytes(completedSize)} / ${fmtBytes(totalSize)}` : `${progress}%`}
              </span>
            </div>
            <Progress value={progress} />
          </div>
        )}

        {message && status !== "pulling" && (
          <div className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm ${status === "error" ? "border border-destructive/30 bg-destructive/10 text-destructive" : status === "success" ? "border border-green-500/30 bg-green-500/10 text-green-600 dark:text-green-400" : "text-muted-foreground"}`}>
            {status === "success" && <CheckCircle className="size-4" />}
            {status === "error" && <AlertCircle className="size-4" />}
            {message}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
