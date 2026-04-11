"use client";

import { useEffect } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[BMT AI OS] Page error:", error);
  }, [error]);

  return (
    <div className="flex min-h-[50vh] items-center justify-center p-6">
      <Card className="w-full max-w-md border-destructive/30">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-destructive">
            <AlertTriangle className="size-5" />
            Something went wrong
          </CardTitle>
          <CardDescription>
            {error.message || "An unexpected error occurred while loading this page."}
          </CardDescription>
        </CardHeader>
        <CardContent className="text-xs text-muted-foreground">
          {error.digest && (
            <p className="font-mono">Error ID: {error.digest}</p>
          )}
          <p className="mt-2">
            This may be caused by the controller API being unreachable or a
            temporary issue. Try refreshing the page.
          </p>
        </CardContent>
        <CardFooter className="gap-2">
          <Button variant="outline" size="sm" onClick={reset}>
            <RefreshCw className="mr-2 size-3.5" />
            Try again
          </Button>
          <Button variant="ghost" size="sm" onClick={() => window.location.href = "/"}>
            Go to Overview
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}
