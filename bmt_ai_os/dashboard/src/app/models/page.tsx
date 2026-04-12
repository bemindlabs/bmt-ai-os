import { fetchModels } from "@/lib/api";
import { ModelManagerClient } from "./model-manager-client";
import { PullModelForm } from "./pull-model-form";

export default async function ModelsPage() {
  const result = await fetchModels().catch(() => null);
  const models = result?.models ?? [];

  return (
    <div className="space-y-8">
      <ModelManagerClient liveModels={models} />
      <PullModelForm
        installedModels={models.map((m) => m.name)}
      />
    </div>
  );
}
