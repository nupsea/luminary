// Type interfaces consumed by Study.tsx and its sub-components.
//
// These mirror the FastAPI response shapes. As the audit-#15
// codegen migration spreads, prefer
//   `import type { components } from "@/types/api"`
//   `type Flashcard = components["schemas"]["FlashcardResponse"]`
// over the handwritten interfaces below. We keep the manual versions
// for now so the Study refactor lands in incremental steps without
// also forcing every field-by-field reconciliation against api.ts.

export interface DocListItem {
  id: string
  title: string
  stage: string
}

export interface Flashcard {
  id: string
  document_id: string
  chunk_id: string
  question: string
  answer: string
  source_excerpt: string
  is_user_edited: boolean
  fsrs_state: string
  reps: number
  lapses: number
  due_date: string | null
  created_at: string
  // S137: Bloom's Taxonomy fields
  flashcard_type: string | null
  bloom_level: number | null
  // S154: cloze deletion text with {{term}} markers; null for non-cloze cards
  cloze_text: string | null
  // S188: section heading for source grounding display
  section_heading: string | null
}

export interface SectionItem {
  id: string
  heading: string
  level: number
  section_order: number
}

export interface DocumentSections {
  sections: SectionItem[]
}

export interface GapResult {
  section_heading: string | null
  weak_card_count: number
  avg_stability: number
  sample_questions: string[]
}

export interface StrugglingCard {
  flashcard_id: string
  document_id: string | null
  question: string
  again_count: number
  source_section_id: string | null
}

// S160: Deck health report types
export interface HealthSection {
  section_id: string
  section_heading: string
  card_count: number
}

export interface DeckHealthReport {
  orphaned: number
  orphaned_ids: string[]
  mastered: number
  mastered_ids: string[]
  stale: number
  stale_ids: string[]
  uncovered_sections: number
  uncovered_section_ids: string[]
  hotspot_sections: HealthSection[]
}

// S184: Search response type
export interface FlashcardSearchResponse {
  items: Flashcard[]
  total: number
  page: number
  page_size: number
}

// S153: Bloom's taxonomy coverage audit types
export interface BloomGap {
  section_id: string
  section_heading: string
  missing_bloom_levels: number[]
}

export interface BloomSectionStat {
  section_heading: string
  by_bloom_level: Record<string, number>
  has_level_3_plus: boolean
}

export interface CoverageReport {
  total_cards: number
  by_bloom_level: Record<string, number>
  by_section: Record<string, BloomSectionStat>
  coverage_score: number
  gaps: BloomGap[]
}
