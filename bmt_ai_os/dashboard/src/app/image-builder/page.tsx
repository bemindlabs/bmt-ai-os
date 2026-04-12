"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import {
  AlertTriangle,
  Check,
  ChevronLeft,
  ChevronRight,
  Cpu,
  HardDrive,
  Info,
  Layers,
  Microchip,
  Monitor,
  Package,
  Play,
  RefreshCw,
  Rocket,
  RotateCcw,
  Save,
  Server,
  WifiOff,
  Zap,
} from "lucide-react";
import {
  fetchTargets,
  fetchPackages,
  fetchTiers,
  fetchPresets,
  fetchProfiles,
  createProfile,
  validateSelection,
  triggerBuild,
  fetchBuildStatus,
  type HardwareTarget,
  type ToolPackage,
  type DeviceTier,
  type BuildPreset,
  type BuildProfile,
  type BuildStatus,
  type ValidationResult,
} from "@/lib/api";

// ── Category metadata ──────────────────────────────────────────────────────

const CATEGORY_META: Record<
  string,
  { label: string; icon: React.ComponentType<{ className?: string }>; color: string }
> = {
  inference:    { label: "Inference",   icon: Microchip, color: "text-violet-500" },
  "coding-cli": { label: "Coding CLI",  icon: Zap,       color: "text-blue-500"   },
  agent:        { label: "Agents",      icon: Server,    color: "text-emerald-500" },
  rag:          { label: "RAG",         icon: HardDrive, color: "text-orange-500"  },
  training:     { label: "Training",    icon: Cpu,       color: "text-rose-500"    },
  utility:      { label: "Utilities",   icon: Monitor,   color: "text-slate-400"   },
};

// ── Helpers ────────────────────────────────────────────────────────────────

function fmtMb(mb: number): string {
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb} MB`;
}

function tierOrder(id: string): number {
  return id === "lite" ? 0 : id === "standard" ? 1 : 2;
}

// ── AcceleratorBadge ───────────────────────────────────────────────────────

function AcceleratorBadge({ accel }: { accel: string }) {
  const colors: Record<string, string> = {
    cuda:  "bg-green-500/15 text-green-400 border-green-500/30",
    hailo: "bg-blue-500/15 text-blue-400 border-blue-500/30",
    rknn:  "bg-orange-500/15 text-orange-400 border-orange-500/30",
    cpu:   "bg-zinc-500/15 text-zinc-400 border-zinc-500/30",
  };
  const key = accel.toLowerCase();
  return (
    <Badge variant="outline" className={cn(colors[key] ?? colors.cpu)}>
      <Zap className="mr-1 size-3" />
      {accel.toUpperCase()}
    </Badge>
  );
}

// ── Step dot ───────────────────────────────────────────────────────────────

function StepDot({
  step,
  current,
  label,
}: {
  step: number;
  current: number;
  label: string;
}) {
  const done   = current > step;
  const active = current === step;
  return (
    <div className="flex items-center gap-2">
      <div
        aria-current={active ? "step" : undefined}
        className={cn(
          "flex size-7 shrink-0 items-center justify-center rounded-full border-2 text-xs font-bold transition-colors",
          done   && "border-green-500 bg-green-500/20 text-green-400",
          active && "border-primary bg-primary/20 text-primary",
          !done && !active && "border-muted text-muted-foreground"
        )}
      >
        {done ? <Check className="size-3.5" /> : step}
      </div>
      <span
        className={cn(
          "hidden text-sm font-medium sm:inline",
          active ? "text-foreground" : "text-muted-foreground"
        )}
      >
        {label}
      </span>
    </div>
  );
}

// ── Package row (native checkbox — no shadcn Checkbox component needed) ────

function PkgRow({
  pkg,
  checked,
  onToggle,
}: {
  pkg: ToolPackage;
  checked: boolean;
  onToggle: () => void;
}) {
  const locked = pkg.required;
  return (
    <button
      type="button"
      disabled={locked}
      onClick={onToggle}
      aria-pressed={checked}
      className={cn(
        "group flex w-full items-start gap-3 rounded-lg border px-3 py-2.5 text-left transition-all",
        checked
          ? "border-primary/50 bg-primary/5"
          : "border-input hover:border-primary/30 hover:bg-muted/30",
        locked && "cursor-default"
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "mt-0.5 flex size-4 shrink-0 items-center justify-center rounded border transition-colors",
          checked
            ? "border-primary bg-primary text-primary-foreground"
            : "border-muted-foreground/40 bg-background"
        )}
      >
        {checked && (
          <svg viewBox="0 0 10 10" className="size-2.5 fill-current">
            <path
              d="M1.5 5l2.5 2.5 4.5-4.5"
              stroke="currentColor"
              strokeWidth="1.5"
              fill="none"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        )}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs font-medium">{pkg.name}</span>
          {locked && (
            <Badge variant="secondary" className="px-1 py-0 text-[9px]">
              required
            </Badge>
          )}
          <span className="ml-auto text-[10px] tabular-nums text-muted-foreground">
            {fmtMb(pkg.size_mb)}
          </span>
        </div>
        <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
          {pkg.description}
        </p>
        {pkg.dependencies.length > 0 && (
          <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">
            deps: {pkg.dependencies.join(", ")}
          </p>
        )}
      </div>
    </button>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────

export default function ImageBuilderPage() {
  const [step, setStep] = useState(1);

  // Remote data
  const [targets,    setTargets]    = useState<HardwareTarget[]>([]);
  const [packages,   setPackages]   = useState<ToolPackage[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [tiers,      setTiers]      = useState<DeviceTier[]>([]);
  const [presets,    setPresets]    = useState<BuildPreset[]>([]);
  const [profiles,   setProfiles]   = useState<BuildProfile[]>([]);
  const [loadState,  setLoadState]  = useState<"loading" | "ok" | "error">("loading");
  const [loadError,  setLoadError]  = useState<string | null>(null);

  // Selections
  const [selectedTarget,   setSelectedTarget]   = useState("");
  const [selectedTier,     setSelectedTier]     = useState("");
  const [selectedPackages, setSelectedPackages] = useState<Set<string>>(new Set());
  const [selectedPreset,   setSelectedPreset]   = useState<string | null>(null);
  const [activeCategory,   setActiveCategory]   = useState("");
  const [profileName,      setProfileName]      = useState("");
  const [profileDesc,      setProfileDesc]      = useState("");

  // Validation & build
  const [validation,  setValidation]  = useState<ValidationResult | null>(null);
  const [validating,  setValidating]  = useState(false);
  const [building,    setBuilding]    = useState(false);
  const [saving,      setSaving]      = useState(false);
  const [buildStatus, setBuildStatus] = useState<BuildStatus | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // ── Load remote data ─────────────────────────────────────────────────────

  const loadData = useCallback(async () => {
    setLoadState("loading");
    setLoadError(null);
    try {
      const [tRes, pRes, tiRes, prRes, profRes] = await Promise.all([
        fetchTargets(),
        fetchPackages(),
        fetchTiers(),
        fetchPresets(),
        fetchProfiles(),
      ]);
      setTargets(tRes.targets);
      setPackages(pRes.packages);
      setCategories(pRes.categories);
      setTiers(tiRes.tiers.sort((a, b) => tierOrder(a.id) - tierOrder(b.id)));
      setPresets(prRes.presets);
      setProfiles(profRes.profiles);
      setActiveCategory(pRes.categories[0] ?? "");
      const required = new Set<string>(pRes.packages.filter((p: ToolPackage) => p.required).map((p: ToolPackage) => p.id));
      setSelectedPackages(required);
      setLoadState("ok");
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Failed to load data");
      setLoadState("error");
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // ── Auto-select default tier when target changes ─────────────────────────

  useEffect(() => {
    if (!selectedTarget || selectedTier) return;
    const t = targets.find((x) => x.id === selectedTarget);
    if (t?.default_tier) setSelectedTier(t.default_tier);
  }, [selectedTarget, targets, selectedTier]);

  // ── Validate on entering step 4 ──────────────────────────────────────────

  useEffect(() => {
    if (step !== 4 || !selectedTarget || !selectedTier) return;
    let cancelled = false;
    const run = async () => {
      setValidating(true);
      setValidation(null);
      try {
        const result = await validateSelection({
          target: selectedTarget,
          tier: selectedTier,
          packages: Array.from(selectedPackages),
        });
        if (!cancelled) setValidation(result);
      } catch {
        // non-fatal
      } finally {
        if (!cancelled) setValidating(false);
      }
    };
    run();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  // ── Poll build status ─────────────────────────────────────────────────────

  useEffect(() => {
    if (
      !buildStatus ||
      buildStatus.status === "completed" ||
      buildStatus.status === "failed"
    )
      return;
    const id = setInterval(async () => {
      try {
        const s = await fetchBuildStatus(buildStatus.id);
        setBuildStatus(s);
        if (s.status === "completed" || s.status === "failed") clearInterval(id);
      } catch {
        clearInterval(id);
      }
    }, 3_000);
    return () => clearInterval(id);
  }, [buildStatus]);

  // ── Derived ───────────────────────────────────────────────────────────────

  const estimatedMb = useMemo(() => {
    let total = 200; // base OS
    for (const pid of Array.from(selectedPackages)) {
      const pkg = packages.find((p) => p.id === pid);
      if (pkg) total += pkg.size_mb;
    }
    return total;
  }, [selectedPackages, packages]);

  const groupedPackages = useMemo(() => {
    const groups: Record<string, ToolPackage[]> = {};
    for (const pkg of packages) {
      (groups[pkg.category] ??= []).push(pkg);
    }
    return groups;
  }, [packages]);

  const targetObj = targets.find((t) => t.id === selectedTarget);
  const tierObj   = tiers.find((t) => t.id === selectedTier);

  // ── Handlers ─────────────────────────────────────────────────────────────

  function togglePackage(pkgId: string) {
    const pkg = packages.find((p) => p.id === pkgId);
    if (pkg?.required) return;
    setSelectedPreset(null);
    setSelectedPackages((prev) => {
      const next = new Set<string>(prev);
      next.has(pkgId) ? next.delete(pkgId) : next.add(pkgId);
      return next;
    });
  }

  function applyPreset(presetId: string) {
    const preset = presets.find((p) => p.id === presetId);
    if (!preset) return;
    setSelectedPreset(presetId);
    const required = packages.filter((p) => p.required).map((p) => p.id);
    setSelectedPackages(new Set<string>([...required, ...preset.packages]));
  }

  async function handleSaveProfile() {
    if (!selectedTarget || !selectedTier || !profileName.trim()) return;
    setSaving(true);
    setActionError(null);
    try {
      await createProfile({
        name: profileName.trim(),
        description: profileDesc.trim() || undefined,
        target: selectedTarget,
        tier: selectedTier,
        packages: Array.from(selectedPackages),
        preset: selectedPreset ?? undefined,
      });
      await loadData();
      setStep(1);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to save profile");
    } finally {
      setSaving(false);
    }
  }

  async function handleSaveAndBuild() {
    if (!selectedTarget || !selectedTier || !profileName.trim()) return;
    setBuilding(true);
    setActionError(null);
    try {
      const res = await createProfile({
        name: profileName.trim(),
        description: profileDesc.trim() || undefined,
        target: selectedTarget,
        tier: selectedTier,
        packages: Array.from(selectedPackages),
        preset: selectedPreset ?? undefined,
      });
      const buildRes = await triggerBuild(res.profile.id);
      setBuildStatus({
        id: buildRes.build_id,
        profile_id: res.profile.id,
        status: "pending",
        manifest_path: buildRes.manifest_path,
        started_at: new Date().toISOString(),
        completed_at: null,
        log: [],
        error: null,
      });
      setStep(5);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Build trigger failed");
    } finally {
      setBuilding(false);
    }
  }

  async function triggerExistingBuild(profileId: string) {
    setActionError(null);
    try {
      const res = await triggerBuild(profileId);
      setBuildStatus({
        id: res.build_id,
        profile_id: profileId,
        status: "pending",
        manifest_path: res.manifest_path,
        started_at: new Date().toISOString(),
        completed_at: null,
        log: [],
        error: null,
      });
      setStep(5);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Build trigger failed");
    }
  }

  function handleReset() {
    setStep(1);
    setSelectedTarget("");
    setSelectedTier("");
    const required = new Set<string>(packages.filter((p) => p.required).map((p) => p.id));
    setSelectedPackages(required);
    setSelectedPreset(null);
    setProfileName("");
    setProfileDesc("");
    setValidation(null);
    setBuildStatus(null);
    setActionError(null);
  }

  // ── Loading / error screens ───────────────────────────────────────────────

  if (loadState === "loading") {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-xl font-semibold">Image Builder</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Configure and build BMT AI OS images for your hardware.
          </p>
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <Card key={i} className="animate-pulse">
              <CardHeader>
                <div className="h-4 w-28 rounded bg-muted" />
              </CardHeader>
              <CardContent>
                <div className="h-14 rounded bg-muted" />
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    );
  }

  if (loadState === "error") {
    return (
      <div className="space-y-6">
        <h1 className="text-xl font-semibold">Image Builder</h1>
        <Card className="border-destructive/50 bg-destructive/5">
          <CardContent className="flex items-start gap-3 py-5">
            <WifiOff className="mt-0.5 size-5 shrink-0 text-destructive" />
            <div className="space-y-2">
              <p className="text-sm font-medium text-destructive">
                Failed to load image builder
              </p>
              <p className="text-xs text-muted-foreground">{loadError}</p>
              <Button variant="outline" size="sm" onClick={loadData}>
                <RefreshCw className="size-3.5" /> Retry
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  // ── Wizard ────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Image Builder</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Configure and build custom BMT AI OS images for your hardware target.
          </p>
        </div>
        {step > 1 && step < 5 && (
          <Button
            variant="ghost"
            size="sm"
            onClick={handleReset}
            aria-label="Reset wizard"
          >
            <RotateCcw className="size-3.5" />
            <span className="hidden sm:inline">Reset</span>
          </Button>
        )}
      </div>

      {/* Step indicator */}
      <nav aria-label="Build steps" className="flex items-center gap-2 overflow-x-auto">
        <StepDot step={1} current={step} label="Hardware" />
        <ChevronRight className="size-3.5 shrink-0 text-muted-foreground/40" />
        <StepDot step={2} current={step} label="Tier" />
        <ChevronRight className="size-3.5 shrink-0 text-muted-foreground/40" />
        <StepDot step={3} current={step} label="Packages" />
        <ChevronRight className="size-3.5 shrink-0 text-muted-foreground/40" />
        <StepDot step={4} current={step} label="Review" />
        {step === 5 && (
          <>
            <ChevronRight className="size-3.5 shrink-0 text-muted-foreground/40" />
            <StepDot step={5} current={step} label="Build" />
          </>
        )}
      </nav>

      {/* Context breadcrumb bar (steps 2-4) */}
      {step > 1 && step <= 4 && (selectedTarget || selectedTier) && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-input bg-muted/30 px-3 py-2">
          <Info className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="text-xs text-muted-foreground">Building for:</span>
          {selectedTarget && (
            <Badge variant="outline" className="text-[11px]">
              {targetObj?.name ?? selectedTarget}
            </Badge>
          )}
          {selectedTier && (
            <Badge variant="outline" className="capitalize text-[11px]">
              {tierObj?.name ?? selectedTier}
            </Badge>
          )}
          {step >= 3 && (
            <Badge variant="secondary" className="text-[11px]">
              {selectedPackages.size} packages &middot; {fmtMb(estimatedMb)}
            </Badge>
          )}
        </div>
      )}

      <Separator />

      {/* ── STEP 1: Hardware Target ─────────────────────────────────────── */}
      {step === 1 && (
        <div className="space-y-5">
          <h2 className="text-base font-semibold">Select Hardware Target</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {targets.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => {
                  setSelectedTarget(t.id);
                  setSelectedTier("");
                  setProfileName(`${t.id}-build`);
                }}
                className={cn(
                  "group flex flex-col gap-3 rounded-xl border p-4 text-left transition-all",
                  selectedTarget === t.id
                    ? "border-primary bg-primary/5 ring-2 ring-primary/30"
                    : "border-input hover:border-primary/40 hover:bg-muted/30"
                )}
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="font-semibold leading-tight">{t.name}</p>
                    <p className="text-xs text-muted-foreground">{t.arch}</p>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <AcceleratorBadge accel={t.accelerator} />
                    {selectedTarget === t.id && (
                      <Check className="size-4 shrink-0 text-primary" />
                    )}
                  </div>
                </div>
                <p className="text-xs leading-relaxed text-muted-foreground">
                  {t.description}
                </p>
                <dl className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px]">
                  {Object.entries(t.specs)
                    .slice(0, 4)
                    .map(([k, v]) => (
                      <div key={k} className="flex gap-1">
                        <dt className="capitalize text-muted-foreground">{k}:</dt>
                        <dd className="truncate font-mono text-foreground/80">{v}</dd>
                      </div>
                    ))}
                </dl>
                <div className="flex flex-wrap gap-1">
                  <Badge variant="outline" className="text-[10px]">
                    {t.image_format}
                  </Badge>
                  <Badge variant="outline" className="text-[10px]">
                    {t.min_storage_gb} GB min
                  </Badge>
                </div>
              </button>
            ))}
          </div>

          <div className="flex justify-end">
            <Button disabled={!selectedTarget} onClick={() => setStep(2)}>
              Next: Device Tier <ChevronRight className="ml-1 size-4" />
            </Button>
          </div>

          {/* Saved profiles */}
          {profiles.length > 0 && (
            <>
              <Separator />
              <div className="space-y-3">
                <h2 className="text-sm font-semibold">Saved Profiles</h2>
                {actionError && (
                  <p className="flex items-center gap-1.5 text-xs text-destructive">
                    <AlertTriangle className="size-3.5" /> {actionError}
                  </p>
                )}
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {profiles.map((p) => (
                    <Card key={p.id} size="sm">
                      <CardHeader>
                        <CardTitle>{p.name}</CardTitle>
                        <CardDescription className="text-xs">
                          {p.target} &middot; {p.tier} &middot; {p.packages.length}{" "}
                          packages
                        </CardDescription>
                      </CardHeader>
                      <CardContent>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => triggerExistingBuild(p.id)}
                        >
                          <Play className="size-3.5" /> Build
                        </Button>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {/* ── STEP 2: Device Tier ─────────────────────────────────────────── */}
      {step === 2 && (
        <div className="space-y-5">
          <h2 className="text-base font-semibold">Select Device Tier</h2>
          <div className="grid gap-4 sm:grid-cols-3">
            {tiers.map((t) => {
              const isRecommended = targetObj?.default_tier === t.id;
              return (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setSelectedTier(t.id)}
                  className={cn(
                    "group relative flex flex-col gap-3 rounded-xl border p-5 text-left transition-all",
                    selectedTier === t.id
                      ? "border-primary bg-primary/5 ring-2 ring-primary/30"
                      : "border-input hover:border-primary/40 hover:bg-muted/30"
                  )}
                >
                  {isRecommended && (
                    <span className="absolute right-3 top-3 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
                      Recommended
                    </span>
                  )}
                  <div className="flex items-center gap-3">
                    <div
                      className={cn(
                        "flex size-10 shrink-0 items-center justify-center rounded-lg text-sm font-bold transition-colors",
                        selectedTier === t.id
                          ? "bg-primary text-primary-foreground"
                          : "bg-muted text-muted-foreground group-hover:bg-primary/10 group-hover:text-primary"
                      )}
                    >
                      {t.id.slice(0, 1).toUpperCase()}
                    </div>
                    <div>
                      <p className="font-semibold">{t.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {t.min_ram_gb}&ndash;{t.max_ram_gb} GB RAM
                      </p>
                    </div>
                  </div>
                  <p className="text-sm text-muted-foreground">{t.description}</p>
                  <dl className="space-y-0.5 text-xs">
                    <div className="flex gap-1">
                      <dt className="text-muted-foreground">Default model:</dt>
                      <dd className="truncate font-mono text-foreground/80">
                        {t.default_model}
                      </dd>
                    </div>
                    <div className="flex gap-1">
                      <dt className="text-muted-foreground">Max image:</dt>
                      <dd className="font-mono text-foreground/80">
                        {t.max_image_size_gb} GB
                      </dd>
                    </div>
                  </dl>
                </button>
              );
            })}
          </div>

          <div className="flex justify-between">
            <Button variant="outline" onClick={() => setStep(1)}>
              <ChevronLeft className="mr-1 size-4" /> Back
            </Button>
            <Button disabled={!selectedTier} onClick={() => setStep(3)}>
              Next: Packages <ChevronRight className="ml-1 size-4" />
            </Button>
          </div>
        </div>
      )}

      {/* ── STEP 3: Package Selection ─────────────────────────────────────── */}
      {step === 3 && (
        <div className="space-y-5">
          <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
            <h2 className="text-base font-semibold">Select Tool Packages</h2>
            <p className="text-xs tabular-nums text-muted-foreground">
              {selectedPackages.size} selected &middot; {fmtMb(estimatedMb)}
            </p>
          </div>

          {/* Presets */}
          {presets.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-muted-foreground">Quick presets:</span>
              {presets.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  title={p.description}
                  onClick={() => applyPreset(p.id)}
                  className={cn(
                    "flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors",
                    selectedPreset === p.id
                      ? "border-primary bg-primary/5 text-primary"
                      : "border-input hover:border-primary/30 hover:bg-muted/30"
                  )}
                >
                  <Layers className="size-3" /> {p.name}
                </button>
              ))}
            </div>
          )}

          {/* Category tabs */}
          <div role="tablist" className="flex flex-wrap gap-1.5">
            {categories.map((cat) => {
              const meta    = CATEGORY_META[cat];
              const CatIcon = meta?.icon ?? Package;
              const count =
                groupedPackages[cat]?.filter((p) => selectedPackages.has(p.id))
                  .length ?? 0;
              const total = groupedPackages[cat]?.length ?? 0;
              return (
                <button
                  key={cat}
                  type="button"
                  role="tab"
                  aria-selected={activeCategory === cat}
                  onClick={() => setActiveCategory(cat)}
                  className={cn(
                    "flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors",
                    activeCategory === cat
                      ? "border-primary bg-primary/5 text-primary"
                      : "border-input text-muted-foreground hover:border-primary/30 hover:text-foreground"
                  )}
                >
                  <CatIcon className={cn("size-3.5", meta?.color)} />
                  {meta?.label ?? cat}
                  <span
                    className={cn(
                      "rounded-full px-1.5 text-[10px] font-semibold tabular-nums",
                      activeCategory === cat
                        ? "bg-primary/15 text-primary"
                        : "bg-muted text-muted-foreground"
                    )}
                  >
                    {count}/{total}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Package list */}
          <div role="tabpanel" className="space-y-2">
            {(groupedPackages[activeCategory] ?? []).length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">
                No packages in this category.
              </p>
            ) : (
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {(groupedPackages[activeCategory] ?? []).map((pkg) => (
                  <PkgRow
                    key={pkg.id}
                    pkg={pkg}
                    checked={selectedPackages.has(pkg.id)}
                    onToggle={() => togglePackage(pkg.id)}
                  />
                ))}
              </div>
            )}
          </div>

          <div className="flex justify-between">
            <Button variant="outline" onClick={() => setStep(2)}>
              <ChevronLeft className="mr-1 size-4" /> Back
            </Button>
            <Button onClick={() => setStep(4)}>
              Next: Review <ChevronRight className="ml-1 size-4" />
            </Button>
          </div>
        </div>
      )}

      {/* ── STEP 4: Review & Build ──────────────────────────────────────── */}
      {step === 4 && (
        <div className="space-y-5">
          <h2 className="text-base font-semibold">Review &amp; Build</h2>

          {/* Summary cards */}
          <div className="grid gap-3 sm:grid-cols-3">
            <Card size="sm">
              <CardHeader>
                <CardDescription>Hardware target</CardDescription>
                <CardTitle>{targetObj?.name ?? selectedTarget}</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-1.5">
                <Badge variant="outline">{targetObj?.arch ?? "—"}</Badge>
                <AcceleratorBadge accel={targetObj?.accelerator ?? "cpu"} />
              </CardContent>
            </Card>
            <Card size="sm">
              <CardHeader>
                <CardDescription>Device tier</CardDescription>
                <CardTitle className="capitalize">
                  {tierObj?.name ?? selectedTier}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-muted-foreground">
                  Max {tierObj?.max_image_size_gb ?? "—"} GB image
                </p>
              </CardContent>
            </Card>
            <Card size="sm">
              <CardHeader>
                <CardDescription>Estimated size</CardDescription>
                <CardTitle className="font-mono">
                  {fmtMb(validation?.estimated_size_mb ?? estimatedMb)}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-1">
                {tierObj && (
                  <Progress
                    value={
                      ((validation?.estimated_size_mb ?? estimatedMb) /
                        (tierObj.max_image_size_gb * 1024)) *
                      100
                    }
                    className="h-1.5"
                  />
                )}
                <p className="text-xs text-muted-foreground">
                  {selectedPackages.size} packages
                </p>
              </CardContent>
            </Card>
          </div>

          {/* Validation */}
          {validating && (
            <div className="flex items-center gap-2 rounded-lg border border-input bg-muted/30 px-4 py-3 text-sm text-muted-foreground">
              <RefreshCw className="size-4 animate-spin" /> Validating selection…
            </div>
          )}
          {validation && validation.warnings.length > 0 && (
            <Card className="border-yellow-500/30 bg-yellow-500/5">
              <CardContent className="space-y-1.5 pt-4">
                {validation.warnings.map((w, i) => (
                  <div
                    key={i}
                    className="flex items-start gap-2 text-sm text-yellow-500"
                  >
                    <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                    {w}
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
          {validation?.valid && validation.warnings.length === 0 && (
            <p className="flex items-center gap-1.5 text-xs text-green-500">
              <Check className="size-3.5" /> Selection is valid and ready to
              build.
            </p>
          )}

          {/* Package summary */}
          <div className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Selected packages
            </p>
            <div className="flex flex-wrap gap-1.5">
              {Array.from(selectedPackages).map((pid) => {
                const pkg = packages.find((p) => p.id === pid);
                return (
                  <Badge
                    key={pid}
                    variant="outline"
                    className="font-mono text-[10px]"
                  >
                    <Package className="mr-1 size-2.5" />
                    {pkg?.name ?? pid}
                  </Badge>
                );
              })}
            </div>
          </div>

          {/* Profile */}
          <Card size="sm">
            <CardHeader>
              <CardTitle>Profile name</CardTitle>
              <CardDescription>
                Name this configuration to save and rebuild later.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <Input
                value={profileName}
                onChange={(e) => setProfileName(e.target.value)}
                placeholder="e.g. pi5-coding-full"
                aria-label="Profile name"
              />
              <Input
                value={profileDesc}
                onChange={(e) => setProfileDesc(e.target.value)}
                placeholder="Description (optional)"
                aria-label="Profile description"
              />
              {actionError && (
                <p className="flex items-center gap-1.5 text-xs text-destructive">
                  <AlertTriangle className="size-3.5" /> {actionError}
                </p>
              )}
            </CardContent>
          </Card>

          <div className="flex flex-wrap justify-between gap-3">
            <Button variant="outline" onClick={() => setStep(3)}>
              <ChevronLeft className="mr-1 size-4" /> Back
            </Button>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                disabled={saving || !profileName.trim()}
                onClick={handleSaveProfile}
              >
                {saving ? (
                  <RefreshCw className="size-3.5 animate-spin" />
                ) : (
                  <Save className="size-3.5" />
                )}
                Save Profile
              </Button>
              <Button
                disabled={building || !profileName.trim()}
                onClick={handleSaveAndBuild}
              >
                {building ? (
                  <RefreshCw className="size-3.5 animate-spin" />
                ) : (
                  <Rocket className="size-3.5" />
                )}
                Save &amp; Build
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ── STEP 5: Build Progress ──────────────────────────────────────── */}
      {step === 5 && buildStatus && (
        <div className="space-y-5">
          <h2 className="text-base font-semibold">Build Progress</h2>

          <Card>
            <CardHeader>
              <div className="flex items-center justify-between gap-2">
                <CardTitle>
                  Build {buildStatus.id.slice(0, 8)}&hellip;
                </CardTitle>
                <Badge
                  variant={
                    buildStatus.status === "completed"
                      ? "default"
                      : buildStatus.status === "failed"
                        ? "destructive"
                        : "secondary"
                  }
                  className="capitalize"
                >
                  {(buildStatus.status === "running" ||
                    buildStatus.status === "pending") && (
                    <RefreshCw className="mr-1 size-3 animate-spin" />
                  )}
                  {buildStatus.status === "completed" && (
                    <Check className="mr-1 size-3" />
                  )}
                  {buildStatus.status}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {(buildStatus.status === "pending" ||
                buildStatus.status === "running") && (
                <Progress value={undefined} className="h-1.5 animate-pulse" />
              )}
              {buildStatus.status === "completed" && (
                <Progress value={100} className="h-1.5" />
              )}

              {buildStatus.error && (
                <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                  {buildStatus.error}
                </div>
              )}

              {buildStatus.log.length > 0 && (
                <div className="max-h-72 overflow-auto rounded-lg bg-zinc-950 p-3 font-mono text-xs text-zinc-300">
                  {buildStatus.log.map((line, i) => (
                    <div key={i}>{line}</div>
                  ))}
                </div>
              )}

              <p className="text-xs text-muted-foreground">
                Started: {new Date(buildStatus.started_at).toLocaleString()}
                {buildStatus.completed_at && (
                  <span>
                    {" "}
                    &middot; Completed:{" "}
                    {new Date(buildStatus.completed_at).toLocaleString()}
                  </span>
                )}
              </p>
            </CardContent>
          </Card>

          {actionError && (
            <p className="flex items-center gap-1.5 text-xs text-destructive">
              <AlertTriangle className="size-3.5" /> {actionError}
            </p>
          )}

          <Button variant="outline" onClick={handleReset}>
            <RotateCcw className="mr-1 size-3.5" /> Start New Build
          </Button>
        </div>
      )}
    </div>
  );
}
