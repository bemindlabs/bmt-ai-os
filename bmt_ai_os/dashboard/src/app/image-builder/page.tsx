"use client";

// ── NOTE: Only import from UI components that exist in src/components/ui/:
// badge, button, card, input, progress, separator, switch, table, tabs
// There is NO Checkbox or Label component — use native HTML + Tailwind.

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
import {
  AlertTriangle,
  Check,
  ChevronRight,
  Cpu,
  HardDrive,
  Layers,
  MemoryStick,
  Package,
  Play,
  RefreshCw,
  Rocket,
  Save,
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

// ── Accelerator icon helper ─────────────────────────────────────────────

function AcceleratorBadge({ accel }: { accel: string }) {
  const colors: Record<string, string> = {
    cuda: "bg-green-500/15 text-green-400 border-green-500/30",
    hailo: "bg-blue-500/15 text-blue-400 border-blue-500/30",
    rknn: "bg-orange-500/15 text-orange-400 border-orange-500/30",
    cpu: "bg-zinc-500/15 text-zinc-400 border-zinc-500/30",
  };
  return (
    <Badge variant="outline" className={colors[accel] ?? colors.cpu}>
      <Zap className="mr-1 size-3" />
      {accel.toUpperCase()}
    </Badge>
  );
}

// ── Step indicator ──────────────────────────────────────────────────────

function StepIndicator({
  step,
  current,
  label,
}: {
  step: number;
  current: number;
  label: string;
}) {
  const done = current > step;
  const active = current === step;
  return (
    <div className="flex items-center gap-2">
      <div
        className={`flex size-8 items-center justify-center rounded-full border-2 text-sm font-bold transition-colors ${
          done
            ? "border-green-500 bg-green-500/20 text-green-400"
            : active
              ? "border-primary bg-primary/20 text-primary"
              : "border-muted text-muted-foreground"
        }`}
      >
        {done ? <Check className="size-4" /> : step}
      </div>
      <span
        className={`text-sm font-medium ${active ? "text-foreground" : "text-muted-foreground"}`}
      >
        {label}
      </span>
    </div>
  );
}

// ── Main page ───────────────────────────────────────────────────────────

export default function ImageBuilderPage() {
  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(true);

  // Data from API
  const [targets, setTargets] = useState<HardwareTarget[]>([]);
  const [packages, setPackages] = useState<ToolPackage[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [tiers, setTiers] = useState<DeviceTier[]>([]);
  const [presets, setPresets] = useState<BuildPreset[]>([]);
  const [profiles, setProfiles] = useState<BuildProfile[]>([]);

  // Selections
  const [selectedTarget, setSelectedTarget] = useState<string>("");
  const [selectedTier, setSelectedTier] = useState<string>("");
  const [selectedPackages, setSelectedPackages] = useState<Set<string>>(
    new Set(),
  );
  const [selectedPreset, setSelectedPreset] = useState<string | null>(null);
  const [profileName, setProfileName] = useState("");

  // Validation & Build
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [validating, setValidating] = useState(false);
  const [building, setBuilding] = useState(false);
  const [buildStatus, setBuildStatus] = useState<BuildStatus | null>(null);

  // ── Load data ─────────────────────────────────────────────────────────

  const loadData = useCallback(async () => {
    setLoading(true);
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
      setTiers(tiRes.tiers);
      setPresets(prRes.presets);
      setProfiles(profRes.profiles);
    } catch {
      // Silently handle — user sees empty state
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // ── Auto-select required packages ─────────────────────────────────────

  useEffect(() => {
    const required = packages.filter((p) => p.required).map((p) => p.id);
    setSelectedPackages((prev) => {
      const next = new Set(prev);
      required.forEach((id) => next.add(id));
      return next;
    });
  }, [packages]);

  // ── Preset application ────────────────────────────────────────────────

  function applyPreset(presetId: string) {
    const preset = presets.find((p) => p.id === presetId);
    if (!preset) return;
    setSelectedPreset(presetId);
    const required = packages.filter((p) => p.required).map((p) => p.id);
    setSelectedPackages(new Set([...required, ...preset.packages]));
  }

  // ── Toggle package ────────────────────────────────────────────────────

  function togglePackage(pkgId: string) {
    const pkg = packages.find((p) => p.id === pkgId);
    if (pkg?.required) return;
    setSelectedPreset(null);
    setSelectedPackages((prev) => {
      const next = new Set(prev);
      if (next.has(pkgId)) next.delete(pkgId);
      else next.add(pkgId);
      return next;
    });
  }

  // ── Validate ──────────────────────────────────────────────────────────

  async function runValidation() {
    if (!selectedTarget || !selectedTier) return;
    setValidating(true);
    try {
      const result = await validateSelection({
        target: selectedTarget,
        tier: selectedTier,
        packages: [...selectedPackages],
      });
      setValidation(result);
    } catch {
      setValidation(null);
    } finally {
      setValidating(false);
    }
  }

  useEffect(() => {
    if (step === 4 && selectedTarget && selectedTier) {
      runValidation();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  // ── Estimated size ────────────────────────────────────────────────────

  const estimatedSize = useMemo(() => {
    let total = 200; // base OS
    for (const pid of selectedPackages) {
      const pkg = packages.find((p) => p.id === pid);
      if (pkg) total += pkg.size_mb;
    }
    return total;
  }, [selectedPackages, packages]);

  // ── Save & Build ──────────────────────────────────────────────────────

  async function handleSaveAndBuild() {
    if (!selectedTarget || !selectedTier || !profileName) return;
    setBuilding(true);
    try {
      const res = await createProfile({
        name: profileName,
        target: selectedTarget,
        tier: selectedTier,
        packages: [...selectedPackages],
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
    } catch {
      // Handle error
    } finally {
      setBuilding(false);
    }
  }

  async function handleSaveOnly() {
    if (!selectedTarget || !selectedTier || !profileName) return;
    try {
      await createProfile({
        name: profileName,
        target: selectedTarget,
        tier: selectedTier,
        packages: [...selectedPackages],
        preset: selectedPreset ?? undefined,
      });
      await loadData();
      setStep(1);
    } catch {
      // Handle error
    }
  }

  // ── Poll build status ─────────────────────────────────────────────────

  useEffect(() => {
    if (!buildStatus || buildStatus.status === "completed" || buildStatus.status === "failed")
      return;
    const interval = setInterval(async () => {
      try {
        const s = await fetchBuildStatus(buildStatus.id);
        setBuildStatus(s);
        if (s.status === "completed" || s.status === "failed") clearInterval(interval);
      } catch {
        clearInterval(interval);
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [buildStatus]);

  // ── Grouped packages ──────────────────────────────────────────────────

  const groupedPackages = useMemo(() => {
    const groups: Record<string, ToolPackage[]> = {};
    for (const pkg of packages) {
      const cat = pkg.category;
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(pkg);
    }
    return groups;
  }, [packages]);

  // ── Render ────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <RefreshCw className="size-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const targetObj = targets.find((t) => t.id === selectedTarget);
  const tierObj = tiers.find((t) => t.id === selectedTier);

  return (
    <div className="mx-auto max-w-5xl space-y-8 p-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Image Builder</h1>
        <p className="text-muted-foreground">
          Configure and build custom BMT AI OS images for your hardware
        </p>
      </div>

      {/* Step indicators */}
      <div className="flex items-center gap-4">
        <StepIndicator step={1} current={step} label="Hardware" />
        <ChevronRight className="size-4 text-muted-foreground" />
        <StepIndicator step={2} current={step} label="Tier" />
        <ChevronRight className="size-4 text-muted-foreground" />
        <StepIndicator step={3} current={step} label="Packages" />
        <ChevronRight className="size-4 text-muted-foreground" />
        <StepIndicator step={4} current={step} label="Review" />
        {buildStatus && (
          <>
            <ChevronRight className="size-4 text-muted-foreground" />
            <StepIndicator step={5} current={step} label="Build" />
          </>
        )}
      </div>

      <Separator />

      {/* ── Step 1: Hardware Target ───────────────────────────────────── */}
      {step === 1 && (
        <div className="space-y-4">
          <h2 className="text-xl font-semibold">Select Hardware Target</h2>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {targets.map((t) => (
              <Card
                key={t.id}
                className={`cursor-pointer transition-all hover:border-primary/50 ${
                  selectedTarget === t.id
                    ? "border-primary bg-primary/5 ring-1 ring-primary"
                    : ""
                }`}
                onClick={() => {
                  setSelectedTarget(t.id);
                  setSelectedTier(t.default_tier);
                  setProfileName(`${t.id}-custom`);
                }}
              >
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between">
                    <CardTitle className="text-base">{t.name}</CardTitle>
                    <AcceleratorBadge accel={t.accelerator} />
                  </div>
                  <CardDescription className="text-xs">
                    {t.description}
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-2 text-xs">
                  <div className="flex items-center gap-2">
                    <Cpu className="size-3.5 text-muted-foreground" />
                    <span>{t.specs.cpu}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <MemoryStick className="size-3.5 text-muted-foreground" />
                    <span>{t.specs.ram}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <HardDrive className="size-3.5 text-muted-foreground" />
                    <span>{t.specs.storage}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Zap className="size-3.5 text-muted-foreground" />
                    <span>{t.specs.accelerator}</span>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>

          <div className="flex justify-end">
            <Button
              disabled={!selectedTarget}
              onClick={() => setStep(2)}
            >
              Next: Device Tier
              <ChevronRight className="ml-1 size-4" />
            </Button>
          </div>
        </div>
      )}

      {/* ── Step 2: Device Tier ──────────────────────────────────────── */}
      {step === 2 && (
        <div className="space-y-4">
          <h2 className="text-xl font-semibold">Select Device Tier</h2>
          <div className="grid gap-4 md:grid-cols-3">
            {tiers.map((t) => (
              <Card
                key={t.id}
                className={`cursor-pointer transition-all hover:border-primary/50 ${
                  selectedTier === t.id
                    ? "border-primary bg-primary/5 ring-1 ring-primary"
                    : ""
                }`}
                onClick={() => setSelectedTier(t.id)}
              >
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between">
                    <CardTitle className="text-base">{t.name}</CardTitle>
                    {targetObj?.default_tier === t.id && (
                      <Badge variant="secondary" className="text-[10px]">
                        Recommended
                      </Badge>
                    )}
                  </div>
                  <CardDescription className="text-xs">
                    {t.description}
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-1.5 text-xs">
                  <div>RAM: {t.min_ram_gb}–{t.max_ram_gb} GB</div>
                  <div>Default model: {t.default_model}</div>
                  <div>Max image: {t.max_image_size_gb} GB</div>
                </CardContent>
              </Card>
            ))}
          </div>

          <div className="flex justify-between">
            <Button variant="outline" onClick={() => setStep(1)}>
              Back
            </Button>
            <Button disabled={!selectedTier} onClick={() => setStep(3)}>
              Next: Packages
              <ChevronRight className="ml-1 size-4" />
            </Button>
          </div>
        </div>
      )}

      {/* ── Step 3: Package Selection ────────────────────────────────── */}
      {step === 3 && (
        <div className="space-y-6">
          <div className="flex items-start justify-between">
            <h2 className="text-xl font-semibold">Select Tool Packages</h2>
            <div className="text-right text-sm text-muted-foreground">
              <div>{selectedPackages.size} packages selected</div>
              <div className="font-mono">~{estimatedSize} MB</div>
            </div>
          </div>

          {/* Preset buttons */}
          <div className="flex flex-wrap gap-2">
            <span className="self-center text-sm text-muted-foreground">
              Quick presets:
            </span>
            {presets.map((p) => (
              <Button
                key={p.id}
                variant={selectedPreset === p.id ? "default" : "outline"}
                size="sm"
                onClick={() => applyPreset(p.id)}
              >
                <Layers className="mr-1 size-3.5" />
                {p.name}
              </Button>
            ))}
          </div>

          <Separator />

          {/* Package groups */}
          {Object.entries(groupedPackages)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([category, pkgs]) => (
              <div key={category}>
                <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                  {category.replace(/-/g, " ")}
                </h3>
                <div className="grid gap-3 md:grid-cols-2">
                  {pkgs.map((pkg) => (
                    <div
                      key={pkg.id}
                      className={`flex items-start gap-3 rounded-lg border p-3 transition-colors ${
                        selectedPackages.has(pkg.id)
                          ? "border-primary/50 bg-primary/5"
                          : "hover:bg-muted/50"
                      } ${pkg.required ? "opacity-90" : "cursor-pointer"}`}
                      onClick={() => togglePackage(pkg.id)}
                    >
                      <input
                        type="checkbox"
                        checked={selectedPackages.has(pkg.id)}
                        disabled={pkg.required}
                        onChange={() => togglePackage(pkg.id)}
                        className="mt-1 size-4 shrink-0 rounded border-input accent-primary"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium">{pkg.name}</span>
                          {pkg.required && (
                            <Badge variant="secondary" className="text-[10px]">
                              Required
                            </Badge>
                          )}
                          <span className="ml-auto text-xs text-muted-foreground">
                            {pkg.size_mb} MB
                          </span>
                        </div>
                        <p className="text-xs text-muted-foreground">
                          {pkg.description}
                        </p>
                        {pkg.dependencies.length > 0 && (
                          <p className="mt-1 text-[10px] text-muted-foreground">
                            Depends on: {pkg.dependencies.join(", ")}
                          </p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}

          <div className="flex justify-between">
            <Button variant="outline" onClick={() => setStep(2)}>
              Back
            </Button>
            <Button onClick={() => setStep(4)}>
              Next: Review
              <ChevronRight className="ml-1 size-4" />
            </Button>
          </div>
        </div>
      )}

      {/* ── Step 4: Review & Build ───────────────────────────────────── */}
      {step === 4 && (
        <div className="space-y-6">
          <h2 className="text-xl font-semibold">Review & Build</h2>

          <div className="grid gap-4 md:grid-cols-3">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Hardware</CardTitle>
              </CardHeader>
              <CardContent className="text-sm">
                <div className="font-medium">{targetObj?.name}</div>
                <div className="text-xs text-muted-foreground">
                  {targetObj?.specs.cpu}
                </div>
                <AcceleratorBadge accel={targetObj?.accelerator ?? "cpu"} />
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Tier</CardTitle>
              </CardHeader>
              <CardContent className="text-sm">
                <div className="font-medium">{tierObj?.name}</div>
                <div className="text-xs text-muted-foreground">
                  {tierObj?.description}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Image Size</CardTitle>
              </CardHeader>
              <CardContent className="text-sm">
                <div className="font-mono text-lg font-bold">
                  {(estimatedSize / 1024).toFixed(1)} GB
                </div>
                <div className="text-xs text-muted-foreground">
                  {selectedPackages.size} packages | {estimatedSize} MB
                </div>
                {tierObj && (
                  <Progress
                    value={(estimatedSize / 1024 / tierObj.max_image_size_gb) * 100}
                    className="mt-2"
                  />
                )}
              </CardContent>
            </Card>
          </div>

          {/* Validation warnings */}
          {validating && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <RefreshCw className="size-4 animate-spin" /> Validating...
            </div>
          )}
          {validation && validation.warnings.length > 0 && (
            <Card className="border-yellow-500/30 bg-yellow-500/5">
              <CardContent className="space-y-1 pt-4">
                {validation.warnings.map((w, i) => (
                  <div
                    key={i}
                    className="flex items-start gap-2 text-sm text-yellow-400"
                  >
                    <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                    {w}
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          {/* Selected packages list */}
          <div>
            <h3 className="mb-2 text-sm font-semibold">Selected Packages</h3>
            <div className="flex flex-wrap gap-1.5">
              {[...selectedPackages].map((pid) => {
                const pkg = packages.find((p) => p.id === pid);
                return (
                  <Badge key={pid} variant="outline" className="text-xs">
                    <Package className="mr-1 size-3" />
                    {pkg?.name ?? pid}
                  </Badge>
                );
              })}
            </div>
          </div>

          {/* Profile name */}
          <div className="space-y-2">
            <label htmlFor="profile-name" className="text-sm font-medium">Profile Name</label>
            <Input
              id="profile-name"
              value={profileName}
              onChange={(e) => setProfileName(e.target.value)}
              placeholder="my-custom-image"
            />
          </div>

          <div className="flex justify-between">
            <Button variant="outline" onClick={() => setStep(3)}>
              Back
            </Button>
            <div className="flex gap-2">
              <Button variant="outline" onClick={handleSaveOnly}>
                <Save className="mr-1 size-4" />
                Save Profile
              </Button>
              <Button
                disabled={building || !profileName}
                onClick={handleSaveAndBuild}
              >
                {building ? (
                  <RefreshCw className="mr-1 size-4 animate-spin" />
                ) : (
                  <Rocket className="mr-1 size-4" />
                )}
                Save & Build Image
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ── Step 5: Build Progress ───────────────────────────────────── */}
      {step === 5 && buildStatus && (
        <div className="space-y-6">
          <h2 className="text-xl font-semibold">Build Progress</h2>

          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">
                  Build {buildStatus.id}
                </CardTitle>
                <Badge
                  variant={
                    buildStatus.status === "completed"
                      ? "default"
                      : buildStatus.status === "failed"
                        ? "destructive"
                        : "secondary"
                  }
                >
                  {buildStatus.status === "running" && (
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
                <Progress value={undefined} className="animate-pulse" />
              )}

              {buildStatus.error && (
                <div className="rounded border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-400">
                  {buildStatus.error}
                </div>
              )}

              {buildStatus.log.length > 0 && (
                <div className="max-h-80 overflow-auto rounded bg-zinc-950 p-3 font-mono text-xs text-zinc-300">
                  {buildStatus.log.map((line, i) => (
                    <div key={i}>{line}</div>
                  ))}
                </div>
              )}

              <div className="text-xs text-muted-foreground">
                Started: {new Date(buildStatus.started_at).toLocaleString()}
                {buildStatus.completed_at && (
                  <>
                    {" | "}Completed:{" "}
                    {new Date(buildStatus.completed_at).toLocaleString()}
                  </>
                )}
              </div>
            </CardContent>
          </Card>

          <Button variant="outline" onClick={() => { setStep(1); setBuildStatus(null); }}>
            Start New Build
          </Button>
        </div>
      )}

      {/* ── Saved Profiles ───────────────────────────────────────────── */}
      {step === 1 && profiles.length > 0 && (
        <div className="space-y-4">
          <Separator />
          <h2 className="text-lg font-semibold">Saved Profiles</h2>
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {profiles.map((p) => (
              <Card key={p.id} className="text-sm">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">{p.name}</CardTitle>
                  <CardDescription className="text-xs">
                    {p.target} | {p.tier} | {p.packages.length} packages
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={async () => {
                        try {
                          const res = await triggerBuild(p.id);
                          setBuildStatus({
                            id: res.build_id,
                            profile_id: p.id,
                            status: "pending",
                            manifest_path: res.manifest_path,
                            started_at: new Date().toISOString(),
                            completed_at: null,
                            log: [],
                            error: null,
                          });
                          setStep(5);
                        } catch {
                          // Handle error
                        }
                      }}
                    >
                      <Play className="mr-1 size-3" />
                      Build
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
