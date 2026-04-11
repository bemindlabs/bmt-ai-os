import { fetchModels } from "@/lib/api";
import { ChatInterface } from "./chat-interface";

export default async function ChatPage() {
  const result = await fetchModels().catch(() => null);
  const models = (result?.models ?? []).map((m) => m.name);

  return (
    <div className="flex h-full flex-col space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Chat</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Interact with loaded models via the OpenAI-compatible API.
        </p>
      </div>
      <ChatInterface models={models} />
    </div>
  );
}
