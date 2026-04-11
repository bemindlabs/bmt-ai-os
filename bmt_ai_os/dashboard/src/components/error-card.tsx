"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

interface ErrorCardProps {
  title?: string;
  message?: string;
  onRetry?: () => void;
}

export function ErrorCard({
  title = "Something went wrong",
  message = "Could not load data. Is the controller running?",
  onRetry,
}: ErrorCardProps) {
  return (
    <Card className="border-destructive/30">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-destructive">
          <AlertTriangle className="size-5" />
          {title}
        </CardTitle>
        <CardDescription>{message}</CardDescription>
      </CardHeader>
      {onRetry && (
        <CardContent>
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RefreshCw className="mr-2 size-3.5" />
            Retry
          </Button>
        </CardContent>
      )}
    </Card>
  );
}

export function LoadingCard({ message = "Loading..." }: { message?: string }) {
  return (
    <Card>
      <CardContent className="flex items-center justify-center py-12">
        <div className="flex items-center gap-3 text-muted-foreground">
          <span className="size-5 animate-spin rounded-full border-2 border-current border-t-transparent" />
          <span className="text-sm">{message}</span>
        </div>
      </CardContent>
    </Card>
  );
}
