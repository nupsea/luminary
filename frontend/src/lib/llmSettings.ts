// One place to read which model a surface will use.
//
// The fetcher lived inside Chat.tsx, so Study could not ask the question at all.
// Both surfaces now read the same endpoint and derive the same "effective model",
// which is what makes the model shown next to a card and next to an answer mean
// the same thing.

import { apiGet } from "@/lib/apiClient"
import type { LLMSettings } from "@/pages/Chat/types"

export type { LLMSettings }

export async function fetchLLMSettings(): Promise<LLMSettings> {
  return apiGet<LLMSettings>("/settings/llm")
}
