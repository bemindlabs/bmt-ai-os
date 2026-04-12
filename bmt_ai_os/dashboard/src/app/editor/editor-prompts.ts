import type { ChatMessage } from "@/lib/api";

/** Strip wrapping markdown code fences from AI response text. */
export function extractCode(raw: string): string {
  const fenceMatch = raw.match(/^```[\w]*\n([\s\S]*?)\n```$/);
  return fenceMatch ? fenceMatch[1] : raw;
}

/** Multi-file system prompt instruction block. */
export const MULTI_FILE_SYSTEM_PROMPT = [
  "When creating or editing multiple files, use this format for each file:",
  "",
  "### FILE: path/to/file.ext",
  "```language",
  "file content here",
  "```",
  "",
  "Include the complete file content for each file. List all files that need to be created or modified.",
].join("\n");

const DEFAULT_SYSTEM_LINES = [
  "You are a coding assistant integrated into a code editor.",
  "The user is editing a file and wants you to generate or modify code.",
  "Respond ONLY with the code — no markdown fences, no explanations, no preamble.",
  "If the user asks to modify existing code, return the complete modified file content.",
  "If the user asks to generate new code, return just the code.",
  "The user can save your output as a new file using the 'Save As' button.",
];

/** Build the default system prompt content for the code editor AI. */
export function buildDefaultSystemContent(opts: {
  filePath: string | null;
  language: string;
  currentDir?: string;
}): string {
  return [
    ...DEFAULT_SYSTEM_LINES,
    opts.filePath ? `Current file: ${opts.filePath} (${opts.language})` : "",
    opts.currentDir ? `Current directory: ${opts.currentDir}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}

/** Build the user message content, including file context if available. */
export function buildUserContent(opts: {
  prompt: string;
  fileContent: string;
  language: string;
}): string {
  return opts.fileContent.trim()
    ? `Here is the current file content:\n\`\`\`${opts.language}\n${opts.fileContent}\n\`\`\`\n\nInstruction: ${opts.prompt}`
    : opts.prompt;
}

/** Build a [system, user] message pair for the editor AI. */
export function buildEditorMessages(opts: {
  prompt: string;
  fileContent: string;
  filePath: string | null;
  language: string;
  currentDir?: string;
  systemContentOverride?: string;
}): ChatMessage[] {
  const systemMessage: ChatMessage = {
    role: "system",
    content:
      opts.systemContentOverride ??
      buildDefaultSystemContent({
        filePath: opts.filePath,
        language: opts.language,
        currentDir: opts.currentDir,
      }),
  };

  const userContent = buildUserContent({
    prompt: opts.prompt,
    fileContent: opts.fileContent,
    language: opts.language,
  });

  return [systemMessage, { role: "user", content: userContent }];
}
