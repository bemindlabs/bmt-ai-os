/**
 * Parse an OpenAI-compatible SSE chunk and extract the delta content.
 *
 * Each line in the chunk that starts with "data:" is parsed as JSON.
 * The `choices[0].delta.content` field is concatenated into the result.
 * Lines with "data: [DONE]" or non-JSON payloads are skipped.
 */
export function parseSSEChunk(chunk: string): string {
  let delta = "";
  for (const line of chunk.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("data:")) continue;
    const payload = trimmed.slice(5).trim();
    if (payload === "[DONE]") continue;
    try {
      const parsed = JSON.parse(payload) as {
        choices?: { delta?: { content?: string } }[];
      };
      const content = parsed.choices?.[0]?.delta?.content;
      if (content) delta += content;
    } catch {
      // Non-JSON SSE line — skip
    }
  }
  return delta;
}
