// Shared types for the Chat page and its sub-modules.

import type { GapCardData } from "@/components/GapResultCard"
import type { SourceCitation } from "@/components/SourceCitationChips"
import type { TeachBackCardData } from "@/components/TeachBackResultCard"

export interface DocListItem {
  id: string
  title: string
}

export interface SuggestionItem {
  id: string
  text: string
}

export interface SuggestionsResponse {
  suggestions: SuggestionItem[]
}

export interface Citation {
  document_title: string | null
  section_heading: string
  page: number
  excerpt: string
  version_mismatch?: boolean
}

export interface WebSource {
  url: string
  title: string
  content: string
  domain: string
  version_info: string
}

export interface WebSearchSettings {
  provider: string
  enabled: boolean
}

// S158: retrieval transparency metadata emitted by backend as 'transparency' SSE event
export interface TransparencyInfo {
  confidence_level: string
  strategy_used: string
  chunk_count: number
  section_count: number
  augmented: boolean
}

export type Confidence = "high" | "medium" | "low"

export interface QuizCardData {
  type: "quiz_question"
  question: string
  context_hint: string
  document_id: string
  error?: string
}

export type AnyCardData = GapCardData | QuizCardData | TeachBackCardData

export interface ChatMessage {
  id: string
  role: "user" | "assistant"
  text: string
  type?: "text" | "card" | "divider"
  cardData?: AnyCardData
  citations?: Citation[]
  confidence?: Confidence
  not_found?: boolean
  isStreaming?: boolean
  image_ids?: string[]
  web_sources?: WebSource[]
  source_citations?: SourceCitation[]
  transparency?: TransparencyInfo
}

export interface SessionPlanItem {
  type: "review" | "gap" | "read"
  title: string
  minutes: number
  action_label: string
  action_target: string
}

export interface SessionPlanResponse {
  total_minutes: number
  items: SessionPlanItem[]
}

export interface CloudProvider {
  name: string
  available: boolean
}

export interface LLMSettings {
  processing_mode: string
  active_model: string
  available_local_models: string[]
  cloud_providers: CloudProvider[]
}
