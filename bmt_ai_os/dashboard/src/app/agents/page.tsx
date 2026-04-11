import { fetchAgents } from "@/lib/api";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AgentSwitcher } from "./agent-switcher";

export default async function AgentsPage() {
  const result = await fetchAgents().catch(() => null);
  const agents = result?.agents ?? [];

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold">Agents</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Manage agent personas. The active agent sets the system prompt and
          default model for new chat sessions.
        </p>
      </div>

      {agents.length === 0 && (
        <Card>
          <CardContent className="pt-4">
            <p className="text-sm text-muted-foreground">
              No agents found. Ensure the controller API is reachable.
            </p>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {agents.map((agent) => (
          <Card key={agent.id}>
            <CardHeader>
              <div className="flex items-start justify-between gap-2">
                <CardTitle className="capitalize">{agent.name}</CardTitle>
                {agent.id === "default" && (
                  <Badge variant="secondary">built-in</Badge>
                )}
              </div>
              <CardDescription className="line-clamp-2">
                {agent.summary}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Model</span>
                  <code className="font-mono text-xs bg-muted px-2 py-0.5 rounded">
                    {agent.model}
                  </code>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Workspace</span>
                  <code className="font-mono text-xs bg-muted px-2 py-0.5 rounded truncate max-w-[160px]">
                    {agent.workspace}
                  </code>
                </div>
              </div>
              <AgentSwitcher agent={agent} />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
