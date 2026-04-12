"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ProviderWizard } from "@/components/provider-wizard";

export function SetupWizardTrigger() {
  const [open, setOpen] = useState(false);
  const router = useRouter();

  function handleComplete() {
    setOpen(false);
    router.refresh();
  }

  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}>
        <Plus className="size-3.5" />
        Setup Wizard
      </Button>

      {open && (
        <ProviderWizard
          onClose={() => setOpen(false)}
          onComplete={handleComplete}
        />
      )}
    </>
  );
}
