// Whether to offer the engine question to a library that already exists.
//
// `EngineChoice` is mounted only by `FirstRunGuide`, which the Hub renders only
// for an empty library. An upgrade meets none of those conditions, so a library
// carrying documents from before the choice existed keeps the `private` default
// and never sees the question -- and `private` there is a default, not a cloud
// anyone declined. The backend tells the two apart with `mode_chosen`, which
// reads whether the settings row exists at all rather than what it says.
//
// Pure, and in lib/, so the rule is unit-tested: Vitest runs in the node
// environment here and components stay untested by convention.

export interface EngineOfferState {
  /** The mode in force. `private` is the only one the offer has anything to say to. */
  mode: string
  /** Whether anyone ever answered the question, either way. */
  modeChosen: boolean
  /** Whether the notice was waved away without answering it. */
  offerDismissed: boolean
}

export function shouldOfferEngineChoice(state: EngineOfferState | undefined): boolean {
  if (!state) return false
  return state.mode === "private" && !state.modeChosen && !state.offerDismissed
}

/**
 * Where a key comes from, per provider.
 *
 * The question asks for a key and, until now, said nothing about where to get
 * one -- which is the step between wanting the fast arm and having it. The
 * console is the only fact stated here: what a key costs and which tier it
 * carries is the provider's to say and changes without notice.
 */
export interface ProviderSetup {
  id: "openai" | "anthropic" | "gemini"
  label: string
  /** The page that issues a key. */
  consoleUrl: string
  consoleLabel: string
}

export const PROVIDER_SETUP: readonly ProviderSetup[] = [
  {
    id: "anthropic",
    label: "Anthropic",
    consoleUrl: "https://console.anthropic.com/settings/keys",
    consoleLabel: "console.anthropic.com",
  },
  {
    id: "openai",
    label: "OpenAI",
    consoleUrl: "https://platform.openai.com/api-keys",
    consoleLabel: "platform.openai.com",
  },
  {
    id: "gemini",
    label: "Google Gemini",
    consoleUrl: "https://aistudio.google.com/app/apikey",
    consoleLabel: "aistudio.google.com",
  },
] as const

export function providerSetup(id: string): ProviderSetup | undefined {
  return PROVIDER_SETUP.find((p) => p.id === id)
}
