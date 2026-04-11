import { fetchProviders } from "@/lib/api";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ProviderSwitcher } from "./provider-switcher";
import { SetupWizardTrigger } from "./setup-wizard-trigger";

export default async function ProvidersPage() {
  const result = await fetchProviders().catch(() => null);
  const providers = result?.providers ?? [];
  const activeProvider = result?.active ?? null;

  return (
    <div className="space-y-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Providers</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Manage and switch between LLM inference providers.
          </p>
        </div>
        <SetupWizardTrigger />
      </div>

      {providers.length === 0 && (
        <Card>
          <CardContent className="pt-4">
            <p className="text-sm text-muted-foreground">
              No providers found. Ensure the controller API is reachable.
            </p>
          </CardContent>
        </Card>
      )}

      {providers.length > 0 && (
        <Card>
          <CardContent className="pt-4">
            <FallbackChain providers={providers} />
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {providers.map((p) => {
          const isActive =
            activeProvider
              ? p.name === activeProvider
              : !!p.active;

          return (
            <Card key={p.name}>
              <CardHeader>
                <div className="flex items-start justify-between gap-2">
                  <CardTitle className="capitalize">{p.name}</CardTitle>
                  <div className="flex flex-col items-end gap-1">
                    <Badge
                      variant={p.healthy ? "default" : "destructive"}
                    >
                      {p.healthy ? "healthy" : "unhealthy"}
                    </Badge>
                    {isActive && (
                      <Badge variant="secondary">active</Badge>
                    )}
                  </div>
                </div>
                <CardDescription>
                  {p.healthy
                    ? "Responding normally"
                    : "Not responding"}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <ProviderSwitcher
                  providerName={p.name}
                  isActive={isActive}
                />
                <ProviderModels
                  providerName={p.name}
                  isHealthy={p.healthy}
                />
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
