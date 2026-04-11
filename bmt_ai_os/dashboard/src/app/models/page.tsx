import Link from "next/link";
import { fetchModels, formatBytes } from "@/lib/api";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PullModelForm } from "./pull-model-form";
import { BookOpen } from "lucide-react";

export default async function ModelsPage() {
  const result = await fetchModels().catch(() => null);
  const models = result?.models ?? result?.data ?? [];

  return (
    <div className="space-y-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Model Manager</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Loaded models available via Ollama.
          </p>
        </div>
        <Link href="/models/catalog">
          <Button variant="outline" size="sm" className="gap-1.5 shrink-0">
            <BookOpen className="size-3.5" />
            View Full Catalog
          </Button>
        </Link>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Loaded Models</CardTitle>
          <CardDescription>
            {models.length === 0
              ? "No models found or API unreachable."
              : `${models.length} model${models.length !== 1 ? "s" : ""} available`}
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {models.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Size</TableHead>
                  <TableHead>Modified</TableHead>
                  <TableHead>Digest</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {models.map((m: Record<string, unknown>) => {
                  const name = (m.name ?? m.id ?? "unknown") as string;
                  const size = (m.size ?? 0) as number;
                  const modified = (m.modified_at ?? m.created ?? "") as string;
                  const digest = (m.digest ?? "") as string;
                  return (
                    <TableRow key={name}>
                      <TableCell className="font-mono text-xs font-medium">
                        {name}
                      </TableCell>
                      <TableCell>
                        {size > 0 ? (
                          <Badge variant="secondary">{formatBytes(size)}</Badge>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {modified
                          ? new Date(
                              typeof modified === "number"
                                ? modified * 1000
                                : modified,
                            ).toLocaleDateString()
                          : "—"}
                      </TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        {digest ? digest.slice(0, 12) : "—"}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <PullModelForm installedModels={models.map((m: Record<string, unknown>) => (m.name ?? m.id ?? "") as string)} />
    </div>
  );
}
