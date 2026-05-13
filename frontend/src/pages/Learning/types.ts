// Shared types for the Learning page and its sub-modules.

export interface SearchMatch {
  chunk_id: string
  document_id: string
  document_title: string
  content_type: string
  section_heading: string
  page: number
  text_excerpt: string
  relevance_score: number
}

export interface DocumentGroup {
  document_id: string
  document_title: string
  content_type: string
  matches: SearchMatch[]
}

export interface DueCountResponse {
  due_today: number
}

export interface SessionListItem {
  accuracy_pct: number | null
}

export interface SessionListResponse {
  items: SessionListItem[]
  total: number
}

export interface StartConceptItem {
  concept: string
  prereq_chain_length: number
  flashcard_count: number
  rationale: string
}

export interface StartConceptsData {
  document_id: string
  concepts: StartConceptItem[]
}
