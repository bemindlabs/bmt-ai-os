// Model catalog data — sourced from providers/*.py pricing tables.
// Pricing is USD per 1M tokens as of 2026-Q2.

export type ProviderName =
  | "openai"
  | "anthropic"
  | "gemini"
  | "groq"
  | "mistral"
  | "ollama"
  | "vllm"
  | "llamacpp";

export type ModelTier = "cloud" | "local";

export interface CatalogModel {
  id: string;
  name: string;
  provider: ProviderName;
  tier: ModelTier;
  contextWindow: number | null; // tokens
  maxOutputTokens: number | null; // tokens
  costInput: number | null; // USD per 1M tokens (null = free/local)
  costOutput: number | null; // USD per 1M tokens (null = free/local)
  quantization: string | null; // e.g. "Q4_K_M", "fp16", null for API
  status: "available" | "preview" | "deprecated";
  description?: string;
}

// ---------------------------------------------------------------------------
// OpenAI models (pricing from openai_provider.py)
// ---------------------------------------------------------------------------
const OPENAI_MODELS: CatalogModel[] = [
  {
    id: "openai/gpt-4o",
    name: "gpt-4o",
    provider: "openai",
    tier: "cloud",
    contextWindow: 128_000,
    maxOutputTokens: 16_384,
    costInput: 2.5,
    costOutput: 10.0,
    quantization: null,
    status: "available",
    description: "Flagship multimodal GPT-4 class model",
  },
  {
    id: "openai/gpt-4o-mini",
    name: "gpt-4o-mini",
    provider: "openai",
    tier: "cloud",
    contextWindow: 128_000,
    maxOutputTokens: 16_384,
    costInput: 0.15,
    costOutput: 0.6,
    quantization: null,
    status: "available",
    description: "Cost-efficient GPT-4o variant",
  },
  {
    id: "openai/gpt-4.1",
    name: "gpt-4.1",
    provider: "openai",
    tier: "cloud",
    contextWindow: 1_000_000,
    maxOutputTokens: 32_768,
    costInput: 2.0,
    costOutput: 8.0,
    quantization: null,
    status: "available",
    description: "Latest GPT-4.1 with 1M context window",
  },
  {
    id: "openai/gpt-4.1-mini",
    name: "gpt-4.1-mini",
    provider: "openai",
    tier: "cloud",
    contextWindow: 1_000_000,
    maxOutputTokens: 32_768,
    costInput: 0.4,
    costOutput: 1.6,
    quantization: null,
    status: "available",
    description: "Cost-efficient GPT-4.1 variant",
  },
  {
    id: "openai/gpt-4.1-nano",
    name: "gpt-4.1-nano",
    provider: "openai",
    tier: "cloud",
    contextWindow: 1_000_000,
    maxOutputTokens: 32_768,
    costInput: 0.1,
    costOutput: 0.4,
    quantization: null,
    status: "available",
    description: "Ultra-low-cost GPT-4.1 nano variant",
  },
  {
    id: "openai/o3-mini",
    name: "o3-mini",
    provider: "openai",
    tier: "cloud",
    contextWindow: 200_000,
    maxOutputTokens: 100_000,
    costInput: 1.1,
    costOutput: 4.4,
    quantization: null,
    status: "available",
    description: "Reasoning model, cost-efficient",
  },
];

// ---------------------------------------------------------------------------
// Anthropic models (pricing from anthropic_provider.py)
// ---------------------------------------------------------------------------
const ANTHROPIC_MODELS: CatalogModel[] = [
  {
    id: "anthropic/claude-opus-4-20250514",
    name: "claude-opus-4-20250514",
    provider: "anthropic",
    tier: "cloud",
    contextWindow: 200_000,
    maxOutputTokens: 32_000,
    costInput: 15.0,
    costOutput: 75.0,
    quantization: null,
    status: "available",
    description: "Most powerful Claude model for complex tasks",
  },
  {
    id: "anthropic/claude-sonnet-4-20250514",
    name: "claude-sonnet-4-20250514",
    provider: "anthropic",
    tier: "cloud",
    contextWindow: 200_000,
    maxOutputTokens: 64_000,
    costInput: 3.0,
    costOutput: 15.0,
    quantization: null,
    status: "available",
    description: "Balanced Claude model — best intelligence per dollar",
  },
  {
    id: "anthropic/claude-haiku-3.5-20241022",
    name: "claude-haiku-3.5-20241022",
    provider: "anthropic",
    tier: "cloud",
    contextWindow: 200_000,
    maxOutputTokens: 8_096,
    costInput: 0.8,
    costOutput: 4.0,
    quantization: null,
    status: "available",
    description: "Fastest and most compact Claude model",
  },
];

// ---------------------------------------------------------------------------
// Gemini models (pricing current as of 2026-Q2)
// ---------------------------------------------------------------------------
const GEMINI_MODELS: CatalogModel[] = [
  {
    id: "gemini/gemini-2.5-pro",
    name: "gemini-2.5-pro",
    provider: "gemini",
    tier: "cloud",
    contextWindow: 1_000_000,
    maxOutputTokens: 65_536,
    costInput: 1.25,
    costOutput: 10.0,
    quantization: null,
    status: "preview",
    description: "Most capable Gemini 2.5 model",
  },
  {
    id: "gemini/gemini-2.0-flash",
    name: "gemini-2.0-flash",
    provider: "gemini",
    tier: "cloud",
    contextWindow: 1_000_000,
    maxOutputTokens: 8_192,
    costInput: 0.1,
    costOutput: 0.4,
    quantization: null,
    status: "available",
    description: "Fast and versatile Gemini 2.0 model",
  },
  {
    id: "gemini/gemini-2.0-flash-lite",
    name: "gemini-2.0-flash-lite",
    provider: "gemini",
    tier: "cloud",
    contextWindow: 1_000_000,
    maxOutputTokens: 8_192,
    costInput: 0.075,
    costOutput: 0.3,
    quantization: null,
    status: "available",
    description: "Lowest cost Gemini model",
  },
];

// ---------------------------------------------------------------------------
// Groq models (pricing from groq_provider.py)
// ---------------------------------------------------------------------------
const GROQ_MODELS: CatalogModel[] = [
  {
    id: "groq/llama-3.3-70b-versatile",
    name: "llama-3.3-70b-versatile",
    provider: "groq",
    tier: "cloud",
    contextWindow: 128_000,
    maxOutputTokens: 32_768,
    costInput: 0.59,
    costOutput: 0.79,
    quantization: null,
    status: "available",
    description: "Llama 3.3 70B on Groq LPU — low latency",
  },
  {
    id: "groq/llama-3.1-8b-instant",
    name: "llama-3.1-8b-instant",
    provider: "groq",
    tier: "cloud",
    contextWindow: 128_000,
    maxOutputTokens: 8_000,
    costInput: 0.05,
    costOutput: 0.08,
    quantization: null,
    status: "available",
    description: "Ultra-fast 8B Llama on Groq LPU",
  },
  {
    id: "groq/mixtral-8x7b-32768",
    name: "mixtral-8x7b-32768",
    provider: "groq",
    tier: "cloud",
    contextWindow: 32_768,
    maxOutputTokens: 32_768,
    costInput: 0.24,
    costOutput: 0.24,
    quantization: null,
    status: "available",
    description: "Mixtral MoE 8x7B on Groq LPU",
  },
  {
    id: "groq/gemma2-9b-it",
    name: "gemma2-9b-it",
    provider: "groq",
    tier: "cloud",
    contextWindow: 8_192,
    maxOutputTokens: 8_192,
    costInput: 0.2,
    costOutput: 0.2,
    quantization: null,
    status: "available",
    description: "Google Gemma2 9B on Groq LPU",
  },
  {
    id: "groq/llama-3.2-11b-vision-preview",
    name: "llama-3.2-11b-vision-preview",
    provider: "groq",
    tier: "cloud",
    contextWindow: 128_000,
    maxOutputTokens: 8_000,
    costInput: 0.18,
    costOutput: 0.18,
    quantization: null,
    status: "preview",
    description: "Llama 3.2 11B vision model on Groq",
  },
  {
    id: "groq/llama-3.2-90b-vision-preview",
    name: "llama-3.2-90b-vision-preview",
    provider: "groq",
    tier: "cloud",
    contextWindow: 128_000,
    maxOutputTokens: 8_000,
    costInput: 0.9,
    costOutput: 0.9,
    quantization: null,
    status: "preview",
    description: "Llama 3.2 90B vision model on Groq",
  },
];

// ---------------------------------------------------------------------------
// Mistral models (pricing from mistral_provider.py)
// ---------------------------------------------------------------------------
const MISTRAL_MODELS: CatalogModel[] = [
  {
    id: "mistral/mistral-small-latest",
    name: "mistral-small-latest",
    provider: "mistral",
    tier: "cloud",
    contextWindow: 32_768,
    maxOutputTokens: 32_768,
    costInput: 0.1,
    costOutput: 0.3,
    quantization: null,
    status: "available",
    description: "Cost-efficient Mistral model",
  },
  {
    id: "mistral/mistral-medium-latest",
    name: "mistral-medium-latest",
    provider: "mistral",
    tier: "cloud",
    contextWindow: 128_000,
    maxOutputTokens: 65_536,
    costInput: 2.7,
    costOutput: 8.1,
    quantization: null,
    status: "available",
    description: "Balanced performance Mistral model",
  },
  {
    id: "mistral/mistral-large-latest",
    name: "mistral-large-latest",
    provider: "mistral",
    tier: "cloud",
    contextWindow: 128_000,
    maxOutputTokens: 65_536,
    costInput: 2.0,
    costOutput: 6.0,
    quantization: null,
    status: "available",
    description: "Most capable Mistral model",
  },
  {
    id: "mistral/codestral-latest",
    name: "codestral-latest",
    provider: "mistral",
    tier: "cloud",
    contextWindow: 256_000,
    maxOutputTokens: 32_768,
    costInput: 0.3,
    costOutput: 0.9,
    quantization: null,
    status: "available",
    description: "Specialized coding model from Mistral",
  },
  {
    id: "mistral/open-mistral-nemo",
    name: "open-mistral-nemo",
    provider: "mistral",
    tier: "cloud",
    contextWindow: 128_000,
    maxOutputTokens: 32_768,
    costInput: 0.15,
    costOutput: 0.15,
    quantization: null,
    status: "available",
    description: "Open-weight Mistral Nemo 12B",
  },
];

// ---------------------------------------------------------------------------
// Ollama local models (representative Qwen-family defaults for BMT AI OS)
// ---------------------------------------------------------------------------
export const OLLAMA_MODEL_DEFAULTS: Record<
  string,
  { contextWindow: number; quantization: string; description: string }
> = {
  "qwen2.5-coder:7b": {
    contextWindow: 131_072,
    quantization: "Q4_K_M",
    description: "Best local coding model — default for BMT AI OS",
  },
  "qwen2.5-coder:14b": {
    contextWindow: 131_072,
    quantization: "Q4_K_M",
    description: "Larger coding model — higher quality, more RAM",
  },
  "qwen2.5-coder:32b": {
    contextWindow: 131_072,
    quantization: "Q4_K_M",
    description: "Full-size coding model — best quality local",
  },
  "qwen2.5:7b": {
    contextWindow: 131_072,
    quantization: "Q4_K_M",
    description: "General-purpose Qwen 2.5 7B",
  },
  "qwen2.5:14b": {
    contextWindow: 131_072,
    quantization: "Q4_K_M",
    description: "General-purpose Qwen 2.5 14B",
  },
  "llama3.2:3b": {
    contextWindow: 131_072,
    quantization: "Q4_K_M",
    description: "Compact Llama 3.2 — fast on edge devices",
  },
  "llama3.2:1b": {
    contextWindow: 131_072,
    quantization: "Q4_K_M",
    description: "Smallest Llama — for ultra-constrained hardware",
  },
  "phi4:14b": {
    contextWindow: 16_384,
    quantization: "Q4_K_M",
    description: "Microsoft Phi-4 14B — strong reasoning, small footprint",
  },
  "mistral:7b": {
    contextWindow: 32_768,
    quantization: "Q4_K_M",
    description: "Mistral 7B — open-weight, well-rounded",
  },
  "deepseek-coder-v2:16b": {
    contextWindow: 163_840,
    quantization: "Q4_K_M",
    description: "DeepSeek Coder V2 — strong at code generation",
  },
};

// ---------------------------------------------------------------------------
// Combined catalog (cloud models only — local models are fetched at runtime)
// ---------------------------------------------------------------------------
export const CLOUD_CATALOG: CatalogModel[] = [
  ...OPENAI_MODELS,
  ...ANTHROPIC_MODELS,
  ...GEMINI_MODELS,
  ...GROQ_MODELS,
  ...MISTRAL_MODELS,
];

export const PROVIDER_LABELS: Record<ProviderName, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  gemini: "Google Gemini",
  groq: "Groq",
  mistral: "Mistral AI",
  ollama: "Ollama (local)",
  vllm: "vLLM (local)",
  llamacpp: "llama.cpp (local)",
};

export const PROVIDER_COLORS: Record<ProviderName, string> = {
  openai: "bg-green-500/15 text-green-400",
  anthropic: "bg-orange-500/15 text-orange-400",
  gemini: "bg-blue-500/15 text-blue-400",
  groq: "bg-purple-500/15 text-purple-400",
  mistral: "bg-sky-500/15 text-sky-400",
  ollama: "bg-teal-500/15 text-teal-400",
  vllm: "bg-indigo-500/15 text-indigo-400",
  llamacpp: "bg-yellow-500/15 text-yellow-400",
};

export function formatContextWindow(tokens: number | null): string {
  if (tokens === null) return "—";
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(0)}M`;
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(0)}K`;
  return String(tokens);
}

export function formatCost(usd: number | null): string {
  if (usd === null) return "Free (local)";
  if (usd === 0) return "$0.00";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}
