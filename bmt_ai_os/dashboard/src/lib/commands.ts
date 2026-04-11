export interface SlashCommand {
  name: string;
  description: string;
  usage: string;
  /** Whether this command takes an argument after it */
  hasArg?: boolean;
}

export const SLASH_COMMANDS: SlashCommand[] = [
  {
    name: "clear",
    description: "Reset the conversation",
    usage: "/clear",
  },
  {
    name: "model",
    description: "Switch the active model",
    usage: "/model <name>",
    hasArg: true,
  },
  {
    name: "rag",
    description: "Toggle RAG (retrieval-augmented generation) on/off",
    usage: "/rag",
  },
  {
    name: "export",
    description: "Download conversation as a Markdown file",
    usage: "/export",
  },
  {
    name: "system",
    description: "Set a system prompt for the conversation",
    usage: "/system <prompt>",
    hasArg: true,
  },
];

/** Return commands whose name starts with the given prefix (case-insensitive). */
export function filterCommands(query: string): SlashCommand[] {
  const lower = query.toLowerCase();
  return SLASH_COMMANDS.filter((cmd) => cmd.name.startsWith(lower));
}

/** Export messages to a Markdown string. */
export function messagesToMarkdown(
  messages: { role: string; content: string }[],
): string {
  const lines: string[] = ["# BMT AI OS — Conversation Export", ""];
  for (const msg of messages) {
    const heading = msg.role === "user" ? "**User**" : "**Assistant**";
    lines.push(`${heading}\n\n${msg.content}`, "");
  }
  return lines.join("\n");
}

/** Trigger a browser download for the given text content. */
export function downloadText(filename: string, content: string): void {
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
