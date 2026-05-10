// HTTP fetchers and message conversion helpers for the Chat page.

import type { PersistedMessage } from "@/lib/chatSessionsApi"
import { API_BASE } from "@/lib/config"

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
  const res = await fetch(`${API_BASE}/documents?sort=last_accessed&page=1&page_size=100`)
  if (!res.ok) return []
  const data = (await res.json()) as { items: DocListItem[] }
  return data.items ?? []
}

export async function fetchLLMSettings(): Promise<LLMSettings> {
  const res = await fetch(`${API_BASE}/settings/llm`)
  if (!res.ok) throw new Error("Failed to fetch LLM settings")
  return res.json() as Promise<LLMSettings>
}

export async function fetchWebSearchSettings(): Promise<WebSearchSettings> {
  const res = await fetch(`${API_BASE}/settings/web-search`)
  if (!res.ok) throw new Error("Failed to fetch web search settings")
  return res.json() as Promise<WebSearchSettings>
}

export async function fetchSessionPlan(): Promise<SessionPlanResponse> {
  const res = await fetch(`${API_BASE}/study/session-plan?minutes=20`)
  if (!res.ok) throw new Error("Failed to fetch session plan")
  return res.json() as Promise<SessionPlanResponse>
}

export async function fetchCachedSuggestions(documentId: string | null): Promise<SuggestionsResponse> {
  const url = documentId
    ? `${API_BASE}/chat/suggestions/cached?document_id=${encodeURIComponent(documentId)}`
    : `${API_BASE}/chat/suggestions/cached`
  const res = await fetch(url)
  if (!res.ok) throw new Error("Failed to fetch cached suggestions")
  return res.json() as Promise<SuggestionsResponse>
}

export async function fetchSuggestions(documentId: string | null): Promise<SuggestionsResponse> {
  const url = documentId
    ? `${API_BASE}/chat/suggestions?document_id=${encodeURIComponent(documentId)}`
    : `${API_BASE}/chat/suggestions`
  const res = await fetch(url)
  if (!res.ok) throw new Error("Failed to fetch suggestions")
  return res.json() as Promise<SuggestionsResponse>
}

export function markSuggestionAsked(id: string): void {
  fetch(`${API_BASE}/chat/suggestions/${id}/asked`, { method: "POST" }).catch(() => {
    /* fire-and-forget */
  })
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
