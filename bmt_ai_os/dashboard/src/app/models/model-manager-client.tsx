"use client";

import { useState, useMemo, useCallback, useTransition } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Search,
  X,
  Circle,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Zap,
  Eye,
  Code2,
  Brain,
  Wrench,
  CloudOff,
  Cloud,
  BookOpen,
} from "lucide-react";
import Link from "next/link";
import {
  CLOUD_CATALOG,
  OLLAMA_MODEL_DEFAULTS,
  PROVIDER_LABELS,
  PROVIDER_COLORS,
  formatContextWindow,
  type CatalogModel,
  type ProviderName,
} from "@/lib/model-catalog";
import { formatBytes } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface LiveOllamaModel {
  name: string;
  size: number;
  modified_at: string;
  digest?: string;
}

export type ProbeStatus =
  | { state: "idle" }
  | { state: "probing" }
  | { state: "ok"; latencyMs: number; reply: string }
  | { state: "error"; message: string };

type Capability = "vision" | "code" | "reasoning" | "tools";

interface EnrichedModel {
  id: string;
  name: string;
  provider: ProviderName;
  tier: "local" | "cloud";
  contextWindow: number | null;
  description?: string;
  quantization: string | null;
  size: number | null; // bytes, local only
  status: "available" | "preview" | "deprecated";
  capabilities: Capability[];
}

// ---------------------------------------------------------------------------
// Capability detection
// ---------------------------------------------------------------------------

function detectCapabilities(model: CatalogModel | EnrichedModel): Capability[] {
  const caps = new Set<Capability>();
  const haystack = `${model.name} ${model.description ?? ""}`.toLowerCase();

  if (
    haystack.includes("vision") ||
    haystack.includes("llava") ||
    haystack.includes("visual") ||
    haystack.includes("multimodal") ||
    haystack.includes("gpt-4o") ||
    haystack.includes("gemini") ||
    haystack.includes("claude") ||
    (haystack.includes("llama") && haystack.includes("11b")) ||
    (haystack.includes("llama") && haystack.includes("90b"))
  ) {
    caps.add("vision");
  }

  if (
    haystack.includes("coder") ||
    haystack.includes("code") ||
    haystack.includes("codestral") ||
    haystack.includes("deepseek") ||
    haystack.includes("phi") ||
    haystack.includes("starcoder") ||
    haystack.includes("qwen2.5") ||
    haystack.includes("gpt-4") ||
    haystack.includes("claude") ||
    haystack.includes("gemini")
  ) {
    caps.add("code");
  }

  if (
    haystack.includes("reasoning") ||
    haystack.includes("o3") ||
    haystack.includes("o1") ||
    haystack.includes("think") ||
    haystack.includes("phi") ||
    haystack.includes("mistral") ||
    haystack.includes("claude-opus") ||
    haystack.includes("gemini-2.5") ||
    haystack.includes("gpt-4.1")
  ) {
    caps.add("reasoning");
  }

  if (
    haystack.includes("tool") ||
    haystack.includes("function") ||
    haystack.includes("gpt-4") ||
    haystack.includes("claude") ||
    haystack.includes("gemini") ||
    haystack.includes("mistral-large") ||
    haystack.includes("llama3") ||
    haystack.includes("groq") ||
    haystack.includes("qwen2.5")
  ) {
    caps.add("tools");
  }

  return Array.from(caps);
}

// ---------------------------------------------------------------------------
// Build enriched model list from Ollama live data
// ---------------------------------------------------------------------------

function buildLocalEnriched(live: LiveOllamaModel[]): EnrichedModel[] {
  return live.map((m) => {
    const defaults = OLLAMA_MODEL_DEFAULTS[m.name];
    const catalog: CatalogModel = {
      id: `ollama/${m.name}`,
      name: m.name,
      provider: "ollama",
      tier: "local",
      contextWindow: defaults?.contextWindow ?? null,
      maxOutputTokens: null,
      costInput: null,
      costOutput: null,
      quantization: defaults?.quantization ?? null,
      status: "available",
      description: defaults?.description,
    };
    return {
      id: `ollama/${m.name}`,
      name: m.name,
      provider: "ollama" as ProviderName,
      tier: "local" as const,
      contextWindow: defaults?.contextWindow ?? null,
      description: defaults?.description,
      quantization: defaults?.quantization ?? null,
      size: m.size ?? null,
      status: "available" as const,
      capabilities: detectCapabilities(catalog),
    };
  });
}

function buildCloudEnriched(): EnrichedModel[] {
  return CLOUD_CATALOG.map((m) => ({
    id: m.id,
    name: m.name,
    provider: m.provider,
    tier: "cloud" as const,
    contextWindow: m.contextWindow,
    description: m.description,
    quantization: m.quantization,
    size: null,
    status: m.status,
    capabilities: detectCapabilities(m),
  }));
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

const CAPABILITY_META: Record<
  Capability,
  { label: string; Icon: React.ComponentType<{ className?: string }> }
> = {
  vision: { label: "Vision", Icon: Eye },
  code: { label: "Code", Icon: Code2 },
  reasoning: { label: "Reasoning", Icon: Brain },
  tools: { label: "Tools", Icon: Wrench },
};

function CapabilityBadge({ cap }: { cap: Capability }) {
  const { label, Icon } = CAPABILITY_META[cap];
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
      <Icon className="size-3" />
      {label}
    </span>
  );
}

function ProviderBadge({ provider }: { provider: ProviderName }) {
  const colorClass =
    PROVIDER_COLORS[provider] ?? "bg-secondary text-secondary-foreground";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${colorClass}`}
    >
      {PROVIDER_LABELS[provider] ?? provider}
    </span>
  );
}

function StatusDot({
  probe,
  modelStatus,
}: {
  probe: ProbeStatus;
  modelStatus: EnrichedModel["status"];
}) {
  if (probe.state === "probing") {
    return <Loader2 className="size-3.5 animate-spin text-muted-foreground" />;
  }
  if (probe.state === "ok") {
    return <CheckCircle2 className="size-3.5 text-green-500" />;
  }
  if (probe.state === "error") {
    return <AlertCircle className="size-3.5 text-destructive" />;
  }
  // idle — show static status from catalog
  if (modelStatus === "deprecated") {
    return <Circle className="size-3.5 text-muted-foreground/40" />;
  }
  if (modelStatus === "preview") {
    return <Circle className="size-3.5 text-yellow-400" />;
  }
  return <Circle className="size-3.5 text-muted-foreground/30" />;
}

function ProbeResult({ probe }: { probe: ProbeStatus }) {
  if (probe.state === "ok") {
    return (
      <span className="text-[11px] text-green-500">
        {probe.latencyMs} ms
      </span>
    );
  }
  if (probe.state === "error") {
    return (
      <span className="max-w-[140px] truncate text-[11px] text-destructive" title={probe.message}>
        {probe.message}
      </span>
    );
  }
  return null;
}

// ---------------------------------------------------------------------------
// Model Card
// ---------------------------------------------------------------------------

function ModelCard({
  model,
  probe,
  onProbe,
  probing,
}: {
  model: EnrichedModel;
  probe: ProbeStatus;
  onProbe: (model: EnrichedModel) => void;
  probing: boolean;
}) {
  return (
    <div className="group relative flex flex-col gap-3 rounded-xl border border-border bg-card p-4 transition-colors hover:border-border/80 hover:bg-card/80">
      {/* Header row */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex items-center gap-1.5">
            <StatusDot probe={probe} modelStatus={model.status} />
            <span className="truncate font-mono text-sm font-semibold leading-tight">
              {model.name}
            </span>
          </div>
          {model.description && (
            <p className="text-[11px] leading-snug text-muted-foreground line-clamp-2">
              {model.description}
            </p>
          )}
        </div>
        <ProviderBadge provider={model.provider} />
      </div>

      {/* Meta row */}
      <div className="flex flex-wrap items-center gap-1.5">
        {model.contextWindow && (
          <Badge variant="outline" className="text-[11px] px-1.5 py-0 font-mono">
            {formatContextWindow(model.contextWindow)} ctx
          </Badge>
        )}
        {model.size && model.size > 0 && (
          <Badge variant="secondary" className="text-[11px] px-1.5 py-0">
            {formatBytes(model.size)}
          </Badge>
        )}
        {model.quantization && (
          <Badge variant="outline" className="text-[11px] px-1.5 py-0 font-mono">
            {model.quantization}
          </Badge>
        )}
        {model.status === "preview" && (
          <Badge
            variant="outline"
            className="text-[11px] px-1.5 py-0 border-yellow-500/50 text-yellow-400"
          >
            Preview
          </Badge>
        )}
        {model.status === "deprecated" && (
          <Badge variant="destructive" className="text-[11px] px-1.5 py-0">
            Deprecated
          </Badge>
        )}
      </div>

      {/* Capability badges */}
      {model.capabilities.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {model.capabilities.map((cap) => (
            <CapabilityBadge key={cap} cap={cap} />
          ))}
        </div>
      )}

      {/* Probe action row */}
      <div className="flex items-center justify-between gap-2 pt-0.5">
        <ProbeResult probe={probe} />
        <Button
          size="sm"
          variant="outline"
          className="h-6 gap-1 px-2 text-[11px]"
          disabled={probing}
          onClick={() => onProbe(model)}
          aria-label={`Test model ${model.name}`}
        >
          {probe.state === "probing" ? (
            <Loader2 className="size-3 animate-spin" />
          ) : (
            <Zap className="size-3" />
          )}
          Test
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Filter bar
// ---------------------------------------------------------------------------

const ALL_CAPABILITIES: Capability[] = ["vision", "code", "reasoning", "tools"];

function FilterBar({
  search,
  onSearch,
  capFilter,
  onCapFilter,
  providerFilter,
  onProviderFilter,
  totalShown,
  totalAll,
  providers,
}: {
  search: string;
  onSearch: (v: string) => void;
  capFilter: Set<Capability>;
  onCapFilter: (cap: Capability) => void;
  providerFilter: string;
  onProviderFilter: (v: string) => void;
  totalShown: number;
  totalAll: number;
  providers: ProviderName[];
}) {
  const hasFilters =
    search !== "" || capFilter.size > 0 || providerFilter !== "all";

  function clearAll() {
    onSearch("");
    ALL_CAPABILITIES.forEach((c) => capFilter.has(c) && onCapFilter(c));
    onProviderFilter("all");
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        {/* Search */}
        <div className="relative min-w-[180px] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="search"
            placeholder="Search models…"
            value={search}
            onChange={(e) => onSearch(e.target.value)}
            className="pl-8 h-8 text-sm"
          />
        </div>

        {/* Provider filter */}
        <select
          value={providerFilter}
          onChange={(e) => onProviderFilter(e.target.value)}
          className="h-8 rounded-lg border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
          aria-label="Filter by provider"
        >
          <option value="all">All providers</option>
          {providers.map((p) => (
            <option key={p} value={p}>
              {PROVIDER_LABELS[p] ?? p}
            </option>
          ))}
        </select>

        {/* Capability toggles */}
        <div className="flex items-center gap-1" role="group" aria-label="Filter by capability">
          {ALL_CAPABILITIES.map((cap) => {
            const { label, Icon } = CAPABILITY_META[cap];
            const active = capFilter.has(cap);
            return (
              <button
                key={cap}
                type="button"
                onClick={() => onCapFilter(cap)}
                aria-pressed={active}
                className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[11px] font-medium transition-colors ${
                  active
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-input text-muted-foreground hover:border-primary/50 hover:text-foreground"
                }`}
              >
                <Icon className="size-3" />
                {label}
              </button>
            );
          })}
        </div>

        {hasFilters && (
          <Button
            variant="ghost"
            size="sm"
            onClick={clearAll}
            className="h-8 gap-1 px-2"
          >
            <X className="size-3" />
            Clear
          </Button>
        )}
      </div>

      <p className="text-xs text-muted-foreground">
        Showing{" "}
        <span className="font-medium text-foreground">{totalShown}</span> of{" "}
        <span className="font-medium text-foreground">{totalAll}</span> models
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main client component
// ---------------------------------------------------------------------------

interface ModelManagerClientProps {
  liveModels: LiveOllamaModel[];
}

export function ModelManagerClient({ liveModels }: ModelManagerClientProps) {
  const [search, setSearch] = useState("");
  const [capFilter, setCapFilter] = useState<Set<Capability>>(new Set());
  const [providerFilter, setProviderFilter] = useState("all");
  const [probeMap, setProbeMap] = useState<Map<string, ProbeStatus>>(new Map());
  const [, startTransition] = useTransition();

  // Build enriched model lists (memo — stable across re-renders)
  const localModels = useMemo(
    () => buildLocalEnriched(liveModels),
    [liveModels],
  );
  const cloudModels = useMemo(() => buildCloudEnriched(), []);
  const allModels = useMemo(
    () => [...localModels, ...cloudModels],
    [localModels, cloudModels],
  );

  // Unique providers across current tab
  const allProviders = useMemo(
    () => Array.from(new Set(allModels.map((m) => m.provider))),
    [allModels],
  );
  const localProviders = useMemo(
    () => Array.from(new Set(localModels.map((m) => m.provider))),
    [localModels],
  );
  const cloudProviders = useMemo(
    () => Array.from(new Set(cloudModels.map((m) => m.provider))),
    [cloudModels],
  );

  function toggleCap(cap: Capability) {
    setCapFilter((prev) => {
      const next = new Set(prev);
      if (next.has(cap)) next.delete(cap);
      else next.add(cap);
      return next;
    });
  }

  function filterModels(models: EnrichedModel[]): EnrichedModel[] {
    let result = models;

    if (search.trim()) {
      const q = search.trim().toLowerCase();
      result = result.filter(
        (m) =>
          m.name.toLowerCase().includes(q) ||
          (m.description ?? "").toLowerCase().includes(q) ||
          (PROVIDER_LABELS[m.provider] ?? "").toLowerCase().includes(q),
      );
    }

    if (providerFilter !== "all") {
      result = result.filter((m) => m.provider === providerFilter);
    }

    if (capFilter.size > 0) {
      result = result.filter((m) =>
        Array.from(capFilter).every((cap) => m.capabilities.includes(cap)),
      );
    }

    return result;
  }

  const filteredAll = useMemo(() => filterModels(allModels), [allModels, search, providerFilter, capFilter]); // eslint-disable-line react-hooks/exhaustive-deps
  const filteredLocal = useMemo(() => filterModels(localModels), [localModels, search, providerFilter, capFilter]); // eslint-disable-line react-hooks/exhaustive-deps
  const filteredCloud = useMemo(() => filterModels(cloudModels), [cloudModels, search, providerFilter, capFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  // Model probe
  const handleProbe = useCallback(
    (model: EnrichedModel) => {
      const key = model.id;
      setProbeMap((prev) => new Map(prev).set(key, { state: "probing" }));

      const modelParam =
        model.tier === "local" ? model.name : `${model.provider}/${model.name}`;

      const start = performance.now();

      startTransition(() => {
        fetch("/v1/chat/completions", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(typeof window !== "undefined" &&
            localStorage.getItem("bmt_auth_token")
              ? {
                  Authorization: `Bearer ${localStorage.getItem("bmt_auth_token")}`,
                }
              : {}),
          },
          body: JSON.stringify({
            model: modelParam,
            messages: [{ role: "user", content: "Say OK" }],
            max_tokens: 5,
            stream: false,
          }),
        })
          .then(async (res) => {
            const elapsed = Math.round(performance.now() - start);
            if (!res.ok) {
              const text = await res.text().catch(() => res.statusText);
              setProbeMap((prev) =>
                new Map(prev).set(key, {
                  state: "error",
                  message: `${res.status}: ${text.slice(0, 80)}`,
                }),
              );
              return;
            }
            const data = await res.json();
            const reply: string =
              data?.choices?.[0]?.message?.content ?? "…";
            setProbeMap((prev) =>
              new Map(prev).set(key, {
                state: "ok",
                latencyMs: elapsed,
                reply,
              }),
            );
          })
          .catch((err: unknown) => {
            setProbeMap((prev) =>
              new Map(prev).set(key, {
                state: "error",
                message:
                  err instanceof Error ? err.message : "Network error",
              }),
            );
          });
      });
    },
    [],
  );

  function getProbe(id: string): ProbeStatus {
    return probeMap.get(id) ?? { state: "idle" };
  }

  function isProbing(id: string): boolean {
    return getProbe(id).state === "probing";
  }

  function CardGrid({ models }: { models: EnrichedModel[] }) {
    if (models.length === 0) {
      return (
        <div className="flex flex-col items-center justify-center py-16 text-center text-muted-foreground">
          <Search className="mb-3 size-8 opacity-30" />
          <p className="text-sm">No models match your filters.</p>
        </div>
      );
    }
    return (
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {models.map((m) => (
          <ModelCard
            key={m.id}
            model={m}
            probe={getProbe(m.id)}
            onProbe={handleProbe}
            probing={isProbing(m.id)}
          />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Page header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Model Manager</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Local and cloud models — browse, filter, and probe latency.
          </p>
        </div>
        <Link href="/models/catalog">
          <Button variant="outline" size="sm" className="gap-1.5 shrink-0">
            <BookOpen className="size-3.5" />
            Full Catalog
          </Button>
        </Link>
      </div>

      {/* Summary chips */}
      <div className="flex flex-wrap gap-3">
        <div className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/40 px-3 py-1 text-xs text-muted-foreground">
          <CloudOff className="size-3.5" />
          <span>
            <span className="font-semibold text-foreground">
              {localModels.length}
            </span>{" "}
            local
          </span>
        </div>
        <div className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/40 px-3 py-1 text-xs text-muted-foreground">
          <Cloud className="size-3.5" />
          <span>
            <span className="font-semibold text-foreground">
              {cloudModels.length}
            </span>{" "}
            cloud
          </span>
        </div>
      </div>

      {/* Tabs + filters + grid */}
      <Tabs defaultValue="all">
        <div className="flex flex-col gap-4">
          <TabsList>
            <TabsTrigger value="all">
              All ({filteredAll.length})
            </TabsTrigger>
            <TabsTrigger value="local">
              Local ({filteredLocal.length})
            </TabsTrigger>
            <TabsTrigger value="cloud">
              Cloud ({filteredCloud.length})
            </TabsTrigger>
          </TabsList>

          {/* Shared filter bar (applies to current tab view) */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">Filter</CardTitle>
            </CardHeader>
            <CardContent>
              <TabsContent value="all">
                <FilterBar
                  search={search}
                  onSearch={setSearch}
                  capFilter={capFilter}
                  onCapFilter={toggleCap}
                  providerFilter={providerFilter}
                  onProviderFilter={setProviderFilter}
                  totalShown={filteredAll.length}
                  totalAll={allModels.length}
                  providers={allProviders}
                />
              </TabsContent>
              <TabsContent value="local">
                <FilterBar
                  search={search}
                  onSearch={setSearch}
                  capFilter={capFilter}
                  onCapFilter={toggleCap}
                  providerFilter={providerFilter}
                  onProviderFilter={setProviderFilter}
                  totalShown={filteredLocal.length}
                  totalAll={localModels.length}
                  providers={localProviders}
                />
              </TabsContent>
              <TabsContent value="cloud">
                <FilterBar
                  search={search}
                  onSearch={setSearch}
                  capFilter={capFilter}
                  onCapFilter={toggleCap}
                  providerFilter={providerFilter}
                  onProviderFilter={setProviderFilter}
                  totalShown={filteredCloud.length}
                  totalAll={cloudModels.length}
                  providers={cloudProviders}
                />
              </TabsContent>
            </CardContent>
          </Card>

          {/* Model grids per tab */}
          <TabsContent value="all">
            <CardGrid models={filteredAll} />
          </TabsContent>
          <TabsContent value="local">
            {localModels.length === 0 ? (
              <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border py-16 text-center">
                <CloudOff className="mb-3 size-8 text-muted-foreground/40" />
                <p className="text-sm text-muted-foreground">
                  No local models loaded.
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Pull a model below to get started.
                </p>
              </div>
            ) : (
              <CardGrid models={filteredLocal} />
            )}
          </TabsContent>
          <TabsContent value="cloud">
            <CardGrid models={filteredCloud} />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
}
