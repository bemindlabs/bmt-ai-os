import { Badge } from "@/components/ui/badge";
import {
  Clock,
  Loader2,
  CheckCircle2,
  XCircle,
  CircleDot,
} from "lucide-react";
import type { TrainingJob } from "@/lib/api";

export function TrainingStatusBadge({ status }: { status: TrainingJob["status"] }) {
  switch (status) {
    case "pending":
      return (
        <Badge variant="outline" className="gap-1.5">
          <Clock className="size-3 opacity-70" />
          Pending
        </Badge>
      );
    case "running":
      return (
        <Badge className="gap-1.5 bg-blue-600 text-white hover:bg-blue-600">
          <Loader2 className="size-3 animate-spin" />
          Running
        </Badge>
      );
    case "completed":
      return (
        <Badge className="gap-1.5 bg-green-600 text-white hover:bg-green-600">
          <CheckCircle2 className="size-3" />
          Completed
        </Badge>
      );
    case "failed":
      return (
        <Badge className="gap-1.5 bg-red-600 text-white hover:bg-red-600">
          <XCircle className="size-3" />
          Failed
        </Badge>
      );
    case "cancelled":
      return (
        <Badge variant="secondary" className="gap-1.5">
          <CircleDot className="size-3 opacity-70" />
          Cancelled
        </Badge>
      );
    default:
      return <Badge variant="outline">{status}</Badge>;
  }
}
