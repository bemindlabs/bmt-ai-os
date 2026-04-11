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

export function PullModelForm() {
  const [modelName, setModelName] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [message, setMessage] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!modelName.trim()) return;

    setStatus("loading");
    setMessage("");

    try {
      const apiBase =
        process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

      const res = await fetch(`${apiBase}/api/pull`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: modelName.trim() }),
      });

      if (!res.ok) {
        throw new Error(`Server responded with ${res.status}`);
      }

      setStatus("success");
      setMessage(`Pull request accepted for "${modelName.trim()}".`);
      setModelName("");
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
          Enter an Ollama model name (e.g. <code className="font-mono text-xs">qwen2.5-coder:7b</code>)
          to pull it onto the device.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="flex items-start gap-3">
          <input
            type="text"
            value={modelName}
            onChange={(e) => setModelName(e.target.value)}
            placeholder="qwen2.5-coder:7b"
            className="h-8 flex-1 rounded-lg border border-input bg-background px-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring/50"
            disabled={status === "loading"}
          />
          <Button type="submit" disabled={status === "loading" || !modelName.trim()}>
            {status === "loading" ? "Pulling…" : "Pull"}
          </Button>
        </form>

        {message && (
          <p
            className={`mt-3 text-sm ${
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
