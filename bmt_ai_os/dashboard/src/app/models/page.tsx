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
import { PullModelForm } from "./pull-model-form";

export default async function ModelsPage() {
  const result = await fetchModels().catch(() => null);
  const models = result?.models ?? [];

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold">Model Manager</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Loaded models available via Ollama.
        </p>
      </div>

      {/* Loaded models table */}
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
                {models.map((m) => (
                  <TableRow key={m.name}>
                    <TableCell className="font-mono text-xs font-medium">
                      {m.name}
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary">{formatBytes(m.size)}</Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {new Date(m.modified_at).toLocaleDateString()}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {m.digest ? m.digest.slice(0, 12) : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Pull new model */}
      <PullModelForm installedModels={models.map((m) => m.name)} />
    </div>
  );
}
