"use client";

import React, { useState, useEffect } from "react";
import { ingestDocuments } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { FolderOpen, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { personaCollection, personaFilesPath } from "./helpers";

type IngestState = "idle" | "loading" | "success" | "error";

export interface IngestTabProps {
  activePersona: string | null;
  personaWorkspacePath: string | null;
}

export function IngestTab({ activePersona, personaWorkspacePath }: IngestTabProps) {
  const defaultPath = personaFilesPath(activePersona, personaWorkspacePath);
  const defaultCollection = personaCollection(activePersona);

  const [folderPath, setFolderPath] = useState(defaultPath);
  const [collection, setCollection] = useState(
    defaultCollection || "default",
  );
  const [state, setState] = useState<IngestState>("idle");
  const [message, setMessage] = useState<string | null>(null);

  // Sync field defaults when persona changes
  useEffect(() => {
    setFolderPath(personaFilesPath(activePersona, personaWorkspacePath));
    setCollection(personaCollection(activePersona) || "default");
    setState("idle");
    setMessage(null);
  }, [activePersona, personaWorkspacePath]);

  async function handleIngest() {
    if (!folderPath.trim()) return;
    setState("loading");
    setMessage(null);
    try {
      const res = await ingestDocuments({
        path: folderPath.trim(),
        collection: collection.trim() || "default",
        recursive: true,
      });
      setState("success");
      setMessage(
        `Accepted: "${res.path}" into collection "${res.collection}". Ingestion runs in the background.`,
      );
    } catch (err) {
      setState("error");
      setMessage(err instanceof Error ? err.message : "Ingest request failed");
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Ingest Documents</CardTitle>
        <CardDescription>
          Provide an absolute folder path on the device. The controller will
          chunk and embed all files recursively.
          {activePersona && (
            <span className="ml-1 text-primary">
              Pre-filled for the <span className="font-medium capitalize">{activePersona}</span> persona workspace.
            </span>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="ingest-path">
              Folder path
            </label>
            <Input
              id="ingest-path"
              placeholder="/data/documents"
              value={folderPath}
              onChange={(e) => setFolderPath(e.target.value)}
              disabled={state === "loading"}
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="ingest-collection">
              Collection name
            </label>
            <Input
              id="ingest-collection"
              placeholder="default"
              value={collection}
              onChange={(e) => setCollection(e.target.value)}
              disabled={state === "loading"}
            />
          </div>
        </div>

        <Button
          onClick={handleIngest}
          disabled={!folderPath.trim() || state === "loading"}
        >
          {state === "loading" ? (
            <>
              <RefreshCw className="mr-2 size-4 animate-spin" />
              Submitting...
            </>
          ) : (
            <>
              <FolderOpen className="mr-2 size-4" />
              Ingest
            </>
          )}
        </Button>

        {message && (
          <p
            className={cn(
              "rounded-md border px-3 py-2 text-sm",
              state === "success"
                ? "border-green-500/30 bg-green-500/10 text-green-700 dark:text-green-400"
                : "border-destructive/30 bg-destructive/10 text-destructive",
            )}
          >
            {message}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
