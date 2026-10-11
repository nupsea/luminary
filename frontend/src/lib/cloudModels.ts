// The rules behind the cloud half of Settings: which key a provider needs,
// which model a provider change lands on, and when Save can run. Pure so they
// are unit-tested; Vitest runs in node here.

export type CloudProvider = "openai" | "anthropic" | "gemini"

export interface CloudModel {
  id: string
  name: string
  cost_input?: number | null
  cost_output?: number | null
  cost_note?: string
  recommended?: boolean
}

export interface KeyFlags {
  has_openai_key: boolean
  has_anthropic_key: boolean
  has_google_key: boolean
}

/** A model that runs on this machine: an Ollama id, prefixed or bare. */
export function isLocalModel(model: string): boolean {
  return !model.includes("/") || model.startsWith("ollama/")
}

/** What the local chat model does under the saved engine mode. */
export function localChatModelHint(mode: string | undefined, providerLabel: string): string {
  if (mode === "hybrid") {
    return `Writes summaries, tags and titles on this machine. Answers and cards use ${providerLabel}, set above, and fall back to this model when ${providerLabel} can't be reached.`
  }
  if (mode === "cloud") {
    return `Cloud mode sends everything to ${providerLabel}, set above. This model answers only when ${providerLabel} can't be reached.`
  }
  return "Answers questions and writes cards on this machine."
}

export function hasKeyFor(provider: string, flags: KeyFlags | undefined): boolean {
  if (!flags) return false
  if (provider === "openai") return flags.has_openai_key
  if (provider === "anthropic") return flags.has_anthropic_key
  if (provider === "gemini") return flags.has_google_key
  return false
}

/** The PATCH field that clears *provider*'s key. */
export function keyField(provider: CloudProvider): "openai_api_key" | "anthropic_api_key" | "google_api_key" {
  return provider === "openai"
    ? "openai_api_key"
    : provider === "anthropic"
      ? "anthropic_api_key"
      : "google_api_key"
}

/**
 * The model a provider switch lands on. The previous provider's model used to
 * stay in the field, so picking Gemini showed `gpt-4o-mini` (I-53 on the server).
 */
export function modelForProvider(models: CloudModel[], current: string): string {
  if (models.some((m) => m.id === current)) return current
  return (models.find((m) => m.recommended) ?? models[0])?.id ?? ""
}

export function formatModelOption(m: CloudModel): string {
  let label = m.name
  if (m.recommended) label += " · recommended"
  if (m.cost_input != null && m.cost_output != null) {
    label += ` · $${m.cost_input} / $${m.cost_output} per 1M tokens`
  }
  if (m.cost_note) label += ` (${m.cost_note})`
  return label
}

/** Why Save cannot run yet, or null when it can. */
export function saveBlocker(args: {
  mode: string
  providerLabel: string
  hasKey: boolean
  pendingKey: boolean
  model: string
}): string | null {
  if (args.mode === "private") return null
  if (!args.hasKey && !args.pendingKey) return `Add a ${args.providerLabel} API key first.`
  if (!args.model.trim()) return "Choose a model."
  return null
}
