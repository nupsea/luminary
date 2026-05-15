export type ContentType =
  | "book"
  | "paper"
  | "conversation"
  | "notes"
  | "code"
  | "audio"
  | "epub"
  | "kindle_clippings"
  | "tech_book"
  | "tech_article"
export type LearningStatus = "not_started" | "summarized" | "flashcards_generated" | "studied"
export type SortOption = "newest" | "oldest" | "alphabetical" | "most-studied" | "last_accessed"
export type ViewMode = "grid" | "list"

export interface DocumentListItem {
  id: string
  title: string
  format: string
  content_type: ContentType
  word_count: number
  page_count: number
  stage: string
  tags: string[]
  created_at: string
  last_accessed_at: string
  summary_one_sentence: string | null
  flashcard_count: number
  learning_status: LearningStatus
  chunk_count: number
  reading_progress_pct: number  // 0.0 to 1.0
  audio_duration_seconds: number | null
  source_url: string | null
  video_title: string | null
  enrichment_status: string | null
  // null = no objectives extracted; 0 = objectives exist but none covered
  objective_progress_pct: number | null
}

export interface DocumentListResponse {
  items: DocumentListItem[]
  total: number
  page: number
  page_size: number
}
