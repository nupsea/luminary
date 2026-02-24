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
