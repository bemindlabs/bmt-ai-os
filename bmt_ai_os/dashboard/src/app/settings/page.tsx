import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { FeatureFlags } from "./feature-flags";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

const PORT_MAP = [
  { port: "6006", service: "TensorBoard" },
  { port: "8000", service: "ChromaDB" },
  { port: "8080", service: "Controller API (OpenAI-compat)" },
  { port: "8888", service: "Jupyter Lab" },
  { port: "9090", service: "Dashboard (this app)" },
  { port: "11434", service: "Ollama" },
];

export default function SettingsPage() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold">Settings</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Configuration, feature flags, and system information.
        </p>
      </div>

      {/* Feature flags */}
      <Card>
        <CardHeader>
          <CardTitle>Feature Flags</CardTitle>
          <CardDescription>
            Toggle experimental features. Changes are local to this session.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <FeatureFlags />
        </CardContent>
      </Card>

      {/* API endpoint info */}
      <Card>
        <CardHeader>
          <CardTitle>API Endpoint</CardTitle>
          <CardDescription>
            The controller API this dashboard connects to.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Base URL</span>
            <code className="font-mono text-xs bg-muted px-2 py-0.5 rounded">
              {API_URL}
            </code>
          </div>
          <Separator />
          <p className="text-xs text-muted-foreground">
            Set <code className="font-mono">NEXT_PUBLIC_API_URL</code> to
            override.
          </p>
        </CardContent>
      </Card>

      {/* Port map */}
      <Card>
        <CardHeader>
          <CardTitle>Service Port Map</CardTitle>
          <CardDescription>
            Default ports for all BMT AI OS services.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-1">
            {PORT_MAP.map(({ port, service }, i) => (
              <div key={port}>
                {i > 0 && <Separator className="my-1" />}
                <div className="flex items-center justify-between py-1 text-sm">
                  <span className="text-muted-foreground">{service}</span>
                  <code className="font-mono text-xs bg-muted px-2 py-0.5 rounded">
                    :{port}
                  </code>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Version */}
      <Card>
        <CardHeader>
          <CardTitle>Version</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-muted-foreground">Dashboard</span>
            <span>v0.1.0-alpha</span>
          </div>
          <Separator />
          <div className="flex justify-between">
            <span className="text-muted-foreground">Architecture</span>
            <span>ARM64 (aarch64)</span>
          </div>
          <Separator />
          <div className="flex justify-between">
            <span className="text-muted-foreground">Default models</span>
            <span>Qwen-family</span>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
