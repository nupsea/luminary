export interface SectionItem {
  id: string
  heading: string
  level: number
  page_start: number
  page_end: number
  section_order: number
  preview: string
}

export interface DocumentDetail {
  id: string
  title: string
  format: string
  content_type: string
  word_count: number
  page_count: number
  stage: string
  tags: string[]
  created_at: string
  last_accessed_at: string
  sections: SectionItem[]
  reading_progress_pct: number  // 0.0 to 1.0
  audio_duration_seconds: number | null
  source_url: string | null
  video_title: string | null
}

export interface AnnotationItem {
  id: string
  document_id: string
  section_id: string
  chunk_id: string | null
  selected_text: string
  start_offset: number
  end_offset: number
  color: "yellow" | "green" | "blue" | "pink"
  note_text: string | null
  created_at: string
}

export type SummaryMode = "one_sentence" | "executive" | "detailed" | "conversation"

export interface SummaryTabDef {
  mode: SummaryMode
  label: string
}

export const SUMMARY_TABS: SummaryTabDef[] = [
  { mode: "one_sentence", label: "One-liner" },
  { mode: "executive", label: "Key Points" },
  { mode: "detailed", label: "Detailed" },
]

export const CONVERSATION_TAB: SummaryTabDef = {
  mode: "conversation",
  label: "Meeting Notes",
}
