import { BASE_URL, getAuthHeader, apiFetch } from "./client";

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

export interface ChatRequest {
  model: string;
  messages: ChatMessage[];
  stream?: boolean;
  temperature?: number;
  max_tokens?: number;
}

export interface ChatResponse {
  id: string;
  object: string;
  created: number;
  model: string;
  choices: {
    index: number;
    message: ChatMessage;
    finish_reason: string;
  }[];
}

export interface ToolCallSummary {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  result_preview: string;
}

export interface ToolChatResult {
  reader: ReadableStreamDefaultReader<string>;
  /** Populated after the stream completes via the X-Tool-Calls header. */
  toolCalls: ToolCallSummary[];
}

export async function sendChat(req: ChatRequest): Promise<ChatResponse> {
  return apiFetch<ChatResponse>("/v1/chat/completions", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function streamChat(
  req: ChatRequest,
  signal?: AbortSignal,
): Promise<ReadableStreamDefaultReader<string>> {
  const res = await fetch(`${BASE_URL}/v1/chat/completions`, {
    method: "POST",
    headers: { ...getAuthHeader(), "Content-Type": "application/json" },
    body: JSON.stringify({ ...req, stream: true }),
    signal,
  });

  if (!res.ok) throw new Error(`${res.status}: ${res.statusText}`);
  if (!res.body) throw new Error("Response body is null");

  return res.body.pipeThrough(new TextDecoderStream()).getReader();
}

/** Tool-augmented chat streaming (BMTOS-154). */
export async function streamChatWithTools(
  req: ChatRequest,
  signal?: AbortSignal,
): Promise<ToolChatResult> {
  const res = await fetch(`${BASE_URL}/api/v1/chat/tools`, {
    method: "POST",
    headers: { ...getAuthHeader(), "Content-Type": "application/json" },
    body: JSON.stringify({ ...req, stream: true }),
    signal,
  });

  if (!res.ok) throw new Error(`${res.status}: ${res.statusText}`);
  if (!res.body) throw new Error("Response body is null");

  // Parse tool call log from the response header (set by the backend).
  let toolCalls: ToolCallSummary[] = [];
  const toolCallsHeader = res.headers.get("X-Tool-Calls");
  if (toolCallsHeader) {
    try {
      toolCalls = JSON.parse(toolCallsHeader) as ToolCallSummary[];
    } catch {
      // ignore malformed header
    }
  }

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  return { reader, toolCalls };
}
