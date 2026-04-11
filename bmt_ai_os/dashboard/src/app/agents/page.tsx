import { fetchAgents } from "@/lib/api";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { AgentSwitcher } from "./agent-switcher";

export default async function AgentsPage() {
  const result = await fetchAgents().catch(() => null);
  const agents = result?.presets ?? [];

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
          <Card key={agent.name}>
            <CardHeader>
              <CardTitle className="capitalize">{agent.name}</CardTitle>
              <CardDescription className="line-clamp-2">
                {agent.description}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <AgentSwitcher agent={agent} />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
