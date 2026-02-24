export type ContentType = "book" | "paper" | "conversation" | "notes" | "code"
export type LearningStatus = "not_started" | "summarized" | "flashcards_generated" | "studied"
export type SortOption = "newest" | "oldest" | "alphabetical" | "most-studied"
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
}
