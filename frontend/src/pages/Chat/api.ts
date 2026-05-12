// HTTP fetchers and message conversion helpers for the Chat page.

import { apiGet, apiPost } from "@/lib/apiClient"
import type { PersistedMessage } from "@/lib/chatSessionsApi"

import type {
  ChatMessage,
  Citation,
  Confidence,
  DocListItem,
  LLMSettings,
  SessionPlanResponse,
  SuggestionsResponse,
  TransparencyInfo,
  WebSearchSettings,
  WebSource,
} from "./types"
import type { SourceCitation } from "@/components/SourceCitationChips"

export async function fetchDocList(): Promise<DocListItem[]> {
  try {
    const data = await apiGet<{ items: DocListItem[] }>("/documents", {
      sort: "last_accessed",
      page: 1,
      page_size: 100,
    })
    return data.items ?? []
  } catch {
    return []
  }
}

export const fetchLLMSettings = (): Promise<LLMSettings> =>
  apiGet<LLMSettings>("/settings/llm")

export const fetchWebSearchSettings = (): Promise<WebSearchSettings> =>
  apiGet<WebSearchSettings>("/settings/web-search")

export const fetchSessionPlan = (): Promise<SessionPlanResponse> =>
  apiGet<SessionPlanResponse>("/study/session-plan", { minutes: 20 })

export const fetchCachedSuggestions = (
  documentId: string | null,
): Promise<SuggestionsResponse> =>
  apiGet<SuggestionsResponse>("/chat/suggestions/cached", {
    document_id: documentId ?? undefined,
  })

export const fetchSuggestions = (
  documentId: string | null,
): Promise<SuggestionsResponse> =>
  apiGet<SuggestionsResponse>("/chat/suggestions", {
    document_id: documentId ?? undefined,
  })

export function markSuggestionAsked(id: string): void {
  // fire-and-forget
  apiPost(`/chat/suggestions/${id}/asked`).catch(() => {})
}

export function persistedToChatMessage(p: PersistedMessage): ChatMessage {
  const extra = (p.extra ?? {}) as Record<string, unknown>
  return {
    id: p.id,
    role: p.role,
    text: p.content,
    citations: (extra["citations"] as Citation[] | undefined) ?? undefined,
    confidence: (extra["confidence"] as Confidence | undefined) ?? undefined,
    not_found: (extra["not_found"] as boolean | undefined) ?? undefined,
    image_ids: (extra["image_ids"] as string[] | undefined) ?? undefined,
    web_sources: (extra["web_sources"] as WebSource[] | undefined) ?? undefined,
    source_citations: (extra["source_citations"] as SourceCitation[] | undefined) ?? undefined,
    transparency: (extra["transparency"] as TransparencyInfo | undefined) ?? undefined,
  }
}
