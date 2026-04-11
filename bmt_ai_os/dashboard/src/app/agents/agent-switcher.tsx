"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { AgentPreset } from "@/lib/api";

const STORAGE_KEY = "bmt_active_agent";

interface AgentSwitcherProps {
  agent: AgentPreset;
}

export function AgentSwitcher({ agent }: AgentSwitcherProps) {
  const [active, setActive] = useState(false);
  const [justSet, setJustSet] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    setActive(stored === agent.name);
  }, [agent.name]);

  function handleSetActive() {
    localStorage.setItem(STORAGE_KEY, agent.name);
    setActive(true);
    setJustSet(true);
    window.dispatchEvent(
      new StorageEvent("storage", {
        key: STORAGE_KEY,
        newValue: agent.name,
        storageArea: localStorage,
      }),
    );
    setTimeout(() => setJustSet(false), 2000);
  }

  const editLink = (
    <Link
      href="/settings"
      className={cn(buttonVariants({ size: "sm", variant: "ghost" }))}
    >
      Edit persona
    </Link>
  );

  if (active) {
    return (
      <div className="flex items-center gap-3">
        <p className="text-xs text-muted-foreground">
          {justSet ? "Active agent set." : "Currently active."}
        </p>
        {editLink}
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3">
      <Button size="sm" variant="outline" onClick={handleSetActive}>
        Set Active
      </Button>
      {editLink}
    </div>
  );
}
