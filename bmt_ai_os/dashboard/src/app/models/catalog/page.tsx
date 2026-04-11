"use client";

import { useState, useMemo, useEffect } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Search,
  X,
  CloudOff,
  Cloud,
} from "lucide-react";
import {
  CLOUD_CATALOG,
  OLLAMA_MODEL_DEFAULTS,
  PROVIDER_LABELS,
  PROVIDER_COLORS,
  formatContextWindow,
  formatCost,
  type CatalogModel,
  type ProviderName,
  type ModelTier,
} from "@/lib/model-catalog";
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
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { fetchModels } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type SortKey = keyof Pick<
  CatalogModel,
  "name" | "provider" | "contextWindow" | "maxOutputTokens" | "costInput" | "costOutput" | "status"
>;

type SortDir = "asc" | "desc" | "none";

interface SortState {
  key: SortKey;
  dir: SortDir;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildLocalModels(ollamaNames: string[]): CatalogModel[] {
  return ollamaNames.map((rawName) => {
    const defaults = OLLAMA_MODEL_DEFAULTS[rawName];
    return {
      id: `ollama/${rawName}`,
      name: rawName,
      provider: "ollama" as ProviderName,
      tier: "local" as ModelTier,
      contextWindow: defaults?.contextWindow ?? null,
      maxOutputTokens: null,
      costInput: null,
      costOutput: null,
      quantization: defaults?.quantization ?? null,
      status: "available" as const,
      description: defaults?.description,
    };
  });
}

function compareValues(a: unknown, b: unknown, dir: SortDir): number {
  if (dir === "none") return 0;
  const nullA = a === null || a === undefined;
  const nullB = b === null || b === undefined;
  if (nullA && nullB) return 0;
  if (nullA) return 1; // nulls last
  if (nullB) return -1;
  const result =
    typeof a === "string" && typeof b === "string"
      ? a.localeCompare(b)
      : (a as number) - (b as number);
  return dir === "asc" ? result : -result;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SortHeader({
  label,
  sortKey,
  sort,
  onSort,
  className,
}: {
  label: string;
  sortKey: SortKey;
  sort: SortState;
  onSort: (key: SortKey) => void;
  className?: string;
}) {
  const isActive = sort.key === sortKey && sort.dir !== "none";
  return (
    <TableHead className={className}>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className="inline-flex items-center gap-1 text-left font-medium hover:text-foreground transition-colors"
        aria-label={`Sort by ${label}`}
      >
        {label}
        {isActive ? (
          sort.dir === "asc" ? (
            <ArrowUp className="size-3" />
          ) : (
            <ArrowDown className="size-3" />
          )
        ) : (
          <ArrowUpDown className="size-3 opacity-40" />
        )}
      </button>
    </TableHead>
  );
}

function ProviderBadge({ provider }: { provider: ProviderName }) {
  const colorClass = PROVIDER_COLORS[provider] ?? "bg-secondary text-secondary-foreground";
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${colorClass}`}>
      {PROVIDER_LABELS[provider] ?? provider}
    </span>
  );
}

function StatusBadge({ status }: { status: CatalogModel["status"] }) {
  if (status === "available") {
    return (
      <Badge variant="secondary" className="text-xs">
        Available
      </Badge>
    );
  }
  if (status === "preview") {
    return (
      <Badge variant="outline" className="text-xs border-yellow-500/50 text-yellow-400">
        Preview
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="text-xs border-destructive/50 text-destructive">
      Deprecated
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Filter controls
// ---------------------------------------------------------------------------

const ALL_PROVIDERS: ProviderName[] = [
  "openai",
  "anthropic",
  "gemini",
  "groq",
  "mistral",
  "ollama",
];

function FilterBar({
  search,
  onSearch,
  providerFilter,
  onProviderFilter,
  tierFilter,
  onTierFilter,
  costMax,
  onCostMax,
  totalShown,
  totalAll,
}: {
  search: string;
  onSearch: (v: string) => void;
  providerFilter: ProviderName | "all";
  onProviderFilter: (v: ProviderName | "all") => void;
  tierFilter: ModelTier | "all";
  onTierFilter: (v: ModelTier | "all") => void;
  costMax: string;
  onCostMax: (v: string) => void;
  totalShown: number;
  totalAll: number;
}) {
  const hasFilters =
    search !== "" ||
    providerFilter !== "all" ||
    tierFilter !== "all" ||
    costMax !== "";

  function clearAll() {
    onSearch("");
    onProviderFilter("all");
    onTierFilter("all");
    onCostMax("");
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        {/* Search */}
        <div className="relative min-w-[200px] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="search"
            placeholder="Search models…"
            value={search}
            onChange={(e) => onSearch(e.target.value)}
            className="pl-8"
          />
        </div>

        {/* Provider filter */}
        <select
          value={providerFilter}
          onChange={(e) => onProviderFilter(e.target.value as ProviderName | "all")}
          className="h-8 rounded-lg border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          aria-label="Filter by provider"
        >
          <option value="all">All providers</option>
          {ALL_PROVIDERS.map((p) => (
            <option key={p} value={p}>
              {PROVIDER_LABELS[p]}
            </option>
          ))}
        </select>

        {/* Tier filter */}
        <select
          value={tierFilter}
          onChange={(e) => onTierFilter(e.target.value as ModelTier | "all")}
          className="h-8 rounded-lg border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          aria-label="Filter by tier"
        >
          <option value="all">Cloud + Local</option>
          <option value="cloud">Cloud only</option>
          <option value="local">Local only</option>
        </select>

        {/* Max cost per 1M input tokens */}
        <div className="relative">
          <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">
            Max $
          </span>
          <Input
            type="number"
            min={0}
            step={0.1}
            placeholder="input cost"
            value={costMax}
            onChange={(e) => onCostMax(e.target.value)}
            className="w-[130px] pl-9"
            aria-label="Maximum input cost per 1M tokens"
          />
        </div>

        {hasFilters && (
          <Button variant="ghost" size="sm" onClick={clearAll} className="gap-1">
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
// Main page
// ---------------------------------------------------------------------------

export default function ModelCatalogPage() {
  const [localModels, setLocalModels] = useState<CatalogModel[]>([]);
  const [loadingLocal, setLoadingLocal] = useState(true);

  // Filters
  const [search, setSearch] = useState("");
  const [providerFilter, setProviderFilter] = useState<ProviderName | "all">("all");
  const [tierFilter, setTierFilter] = useState<ModelTier | "all">("all");
  const [costMax, setCostMax] = useState("");

  // Sort
  const [sort, setSort] = useState<SortState>({ key: "provider", dir: "asc" });

  // Fetch local (Ollama) models
  useEffect(() => {
    fetchModels()
      .then((res) => {
        setLocalModels(buildLocalModels(res.models.map((m) => m.name)));
      })
      .catch(() => {
        // Fallback: show well-known Qwen defaults
        setLocalModels(
          buildLocalModels(Object.keys(OLLAMA_MODEL_DEFAULTS).slice(0, 5))
        );
      })
      .finally(() => setLoadingLocal(false));
  }, []);

  const allModels = useMemo(
    () => [...CLOUD_CATALOG, ...localModels],
    [localModels]
  );

  function cycleSort(key: SortKey) {
    setSort((prev) => {
      if (prev.key !== key) return { key, dir: "asc" };
      if (prev.dir === "asc") return { key, dir: "desc" };
      if (prev.dir === "desc") return { key, dir: "none" };
      return { key, dir: "asc" };
    });
  }

  const filteredAndSorted = useMemo(() => {
    let models = allModels;

    if (search.trim()) {
      const q = search.trim().toLowerCase();
      models = models.filter(
        (m) =>
          m.name.toLowerCase().includes(q) ||
          (PROVIDER_LABELS[m.provider] ?? m.provider).toLowerCase().includes(q) ||
          (m.description ?? "").toLowerCase().includes(q)
      );
    }

    if (providerFilter !== "all") {
      models = models.filter((m) => m.provider === providerFilter);
    }

    if (tierFilter !== "all") {
      models = models.filter((m) => m.tier === tierFilter);
    }

    if (costMax !== "" && !isNaN(parseFloat(costMax))) {
      const maxVal = parseFloat(costMax);
      models = models.filter(
        (m) => m.costInput === null || m.costInput <= maxVal
      );
    }

    if (sort.dir !== "none") {
      models = [...models].sort((a, b) =>
        compareValues(a[sort.key], b[sort.key], sort.dir)
      );
    }

    return models;
  }, [allModels, search, providerFilter, tierFilter, costMax, sort]);

  const cloudCount = filteredAndSorted.filter((m) => m.tier === "cloud").length;
  const localCount = filteredAndSorted.filter((m) => m.tier === "local").length;

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Link
              href="/models"
              className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
            >
              <ArrowLeft className="size-3.5" />
              Model Manager
            </Link>
          </div>
          <h1 className="mt-1 text-xl font-semibold">Model Catalog</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            All models across all providers with pricing, context window, and
            quantization info.
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-3 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <Cloud className="size-3.5" />
            {cloudCount} cloud
          </span>
          <span className="inline-flex items-center gap-1.5">
            <CloudOff className="size-3.5" />
            {localCount} local{loadingLocal ? "…" : ""}
          </span>
        </div>
      </div>

      <Card>
        <CardHeader className="pb-4">
          <CardTitle className="text-base">All Models</CardTitle>
          <CardDescription>
            Cloud pricing shown as USD per 1M tokens. Local models run free on-device.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <FilterBar
            search={search}
            onSearch={setSearch}
            providerFilter={providerFilter}
            onProviderFilter={setProviderFilter}
            tierFilter={tierFilter}
            onTierFilter={setTierFilter}
            costMax={costMax}
            onCostMax={setCostMax}
            totalShown={filteredAndSorted.length}
            totalAll={allModels.length}
          />

          <div className="rounded-lg border border-border overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow>
                  <SortHeader
                    label="Model Name"
                    sortKey="name"
                    sort={sort}
                    onSort={cycleSort}
                    className="w-[220px]"
                  />
                  <SortHeader
                    label="Provider"
                    sortKey="provider"
                    sort={sort}
                    onSort={cycleSort}
                    className="w-[150px]"
                  />
                  <SortHeader
                    label="Context"
                    sortKey="contextWindow"
                    sort={sort}
                    onSort={cycleSort}
                    className="w-[90px]"
                  />
                  <SortHeader
                    label="Max Out"
                    sortKey="maxOutputTokens"
                    sort={sort}
                    onSort={cycleSort}
                    className="w-[90px]"
                  />
                  <SortHeader
                    label="Input /1M"
                    sortKey="costInput"
                    sort={sort}
                    onSort={cycleSort}
                    className="w-[110px]"
                  />
                  <SortHeader
                    label="Output /1M"
                    sortKey="costOutput"
                    sort={sort}
                    onSort={cycleSort}
                    className="w-[110px]"
                  />
                  <TableHead className="w-[100px]">Quantization</TableHead>
                  <SortHeader
                    label="Status"
                    sortKey="status"
                    sort={sort}
                    onSort={cycleSort}
                    className="w-[100px]"
                  />
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredAndSorted.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={8} className="py-10 text-center text-muted-foreground">
                      No models match your filters.
                    </TableCell>
                  </TableRow>
                ) : (
                  filteredAndSorted.map((model) => (
                    <TableRow key={model.id}>
                      <TableCell>
                        <div className="flex flex-col gap-0.5">
                          <span className="font-mono text-xs font-medium leading-snug">
                            {model.name}
                          </span>
                          {model.description && (
                            <span className="text-[11px] text-muted-foreground leading-snug max-w-[200px] whitespace-normal">
                              {model.description}
                            </span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <ProviderBadge provider={model.provider} />
                      </TableCell>
                      <TableCell className="text-xs font-mono text-muted-foreground">
                        {formatContextWindow(model.contextWindow)}
                      </TableCell>
                      <TableCell className="text-xs font-mono text-muted-foreground">
                        {model.maxOutputTokens
                          ? formatContextWindow(model.maxOutputTokens)
                          : "—"}
                      </TableCell>
                      <TableCell>
                        {model.costInput === null ? (
                          <span className="text-xs font-medium text-teal-400">
                            Free (local)
                          </span>
                        ) : (
                          <span className="font-mono text-xs text-foreground">
                            {formatCost(model.costInput)}
                          </span>
                        )}
                      </TableCell>
                      <TableCell>
                        {model.costOutput === null ? (
                          <span className="text-xs font-medium text-teal-400">
                            Free (local)
                          </span>
                        ) : (
                          <span className="font-mono text-xs text-foreground">
                            {formatCost(model.costOutput)}
                          </span>
                        )}
                      </TableCell>
                      <TableCell>
                        {model.quantization ? (
                          <Badge variant="outline" className="font-mono text-[10px] px-1.5">
                            {model.quantization}
                          </Badge>
                        ) : (
                          <span className="text-xs text-muted-foreground">API</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={model.status} />
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>

          <p className="text-[11px] text-muted-foreground">
            Pricing is indicative as of 2026-Q2 and may change. Local models (Ollama) are free to run on-device.
            Context windows reflect published maximums; actual usable context may vary.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
