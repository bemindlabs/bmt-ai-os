import { fetchModels } from "@/lib/api";
import { ChatInterface } from "./chat-interface";

export default async function ChatPage() {
  const result = await fetchModels().catch(() => null);
  const models = (result?.models ?? []).map((m) => m.name);

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <div className="shrink-0">
        <h1 className="text-xl font-semibold">Chat</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Interact with loaded models via the OpenAI-compatible API.
        </p>
      </div>
      {/* ChatInterface owns its own sidebar + main layout */}
      <div className="flex min-h-0 flex-1 overflow-hidden rounded-lg border border-border">
        <ChatInterface models={models} />
      </div>
    </div>
  );
}
