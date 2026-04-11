"use client";

import { useState } from "react";
import { setActiveProvider } from "@/lib/api";
import { Button } from "@/components/ui/button";

interface ProviderSwitcherProps {
  providerName: string;
  isActive: boolean;
}

export function ProviderSwitcher({ providerName, isActive }: ProviderSwitcherProps) {
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<"idle" | "success" | "error">("idle");

  async function handleSwitch() {
    setLoading(true);
    setStatus("idle");
    try {
      await setActiveProvider(providerName);
      setStatus("success");
    } catch {
      setStatus("error");
    } finally {
      setLoading(false);
    }
  }

  if (isActive) {
    return (
      <p className="text-xs text-muted-foreground">Currently active provider.</p>
    );
  }

  return (
    <div className="space-y-2">
      <Button
        size="sm"
        variant="outline"
        onClick={handleSwitch}
        disabled={loading}
      >
        {loading ? "Switching…" : "Set as Active"}
      </Button>
      {status === "success" && (
        <p className="text-xs text-muted-foreground">
          Provider switched. Reload to verify.
        </p>
      )}
      {status === "error" && (
        <p className="text-xs text-destructive">Failed to switch provider.</p>
      )}
    </div>
  );
}
