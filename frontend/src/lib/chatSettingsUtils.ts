// Pure utility functions for Chat settings -- testable in Vitest node env.
// No React or store imports here.

export interface LLMSettingsForUtils {
  processing_mode: string
  active_model: string
  available_local_models: string[]
}

/**
 * Returns the list of model options for the model selector.
 * Returns empty array in cloud mode (backend handles routing).
 * Falls back to active_model when no local models are enumerated.
 */
export function buildModelOptions(settings: LLMSettingsForUtils | undefined): string[] {
  if (!settings) return []
  if (settings.processing_mode === "cloud") return []
  const opts = settings.available_local_models
  return opts.length > 0 ? opts : (settings.active_model ? [settings.active_model] : [])
}

/**
 * Returns a human-readable label for a transparency confidence level.
 */
export function buildTransparencyIconLabel(confidenceLevel: string): string {
  switch (confidenceLevel) {
    case "high": return "High confidence"
    case "medium": return "Medium confidence"
    case "low": return "Low confidence"
    default: return "Unknown confidence"
  }
}

/**
 * The sections that live inside ChatSettingsDrawer (not the Chat header).
 * Encodes the architectural invariant: model selector, web search, and scope
 * are drawer sections -- NOT header controls.
 */
export const DRAWER_SECTIONS = ["scope", "model", "web_search"] as const
export type DrawerSection = (typeof DRAWER_SECTIONS)[number]

/**
 * Default open state for the TransparencyPanel.
 * false = collapsed by default; user must click the 'i' icon to expand.
 */
export const TRANSPARENCY_DEFAULT_OPEN = false
