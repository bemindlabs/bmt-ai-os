"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { FolderOpen, Check } from "lucide-react";
import { useWorkspace } from "@/hooks/use-workspace";

export function WorkspaceConfig() {
  const { workspace, setWorkspace } = useWorkspace();
  const [input, setInput] = useState(workspace);
  const [saved, setSaved] = useState(false);

  // Sync input when workspace loads async
  if (input === "" && workspace !== "") {
    setInput(workspace);
  }

  function handleSave() {
    const trimmed = input.trim();
    if (!trimmed) return;
    setWorkspace(trimmed);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FolderOpen className="size-5" />
          Workspace Directory
        </CardTitle>
        <CardDescription>
          Default directory for the Code Editor and File Manager. Set{" "}
          <code className="font-mono text-xs">BMT_WORKSPACE_DIR</code> on the
          server to change the system default.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="/home/user/workspace"
            className="flex-1 font-mono text-sm"
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSave();
            }}
          />
          <Button
            variant="outline"
            size="sm"
            onClick={handleSave}
            disabled={!input.trim() || input.trim() === workspace}
          >
            {saved ? (
              <>
                <Check className="mr-1.5 size-3.5" />
                Saved
              </>
            ) : (
              "Save"
            )}
          </Button>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          Changes apply immediately to the Editor and Files tabs. The directory
          is auto-created on the server if it doesn&apos;t exist.
        </p>
      </CardContent>
    </Card>
  );
}
