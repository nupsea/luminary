// Type interfaces consumed by Notes.tsx and its sub-components.
// As audit-#15's OpenAPI codegen migration spreads, prefer
//   `import type { components } from "@/types/api"`
// over the handwritten interfaces below.

export interface Note {
  id: string
  document_id: string | null
  chunk_id: string | null
  content: string
  tags: string[]
  group_name: string | null
  collection_ids: string[]
  source_document_ids: string[]
  created_at: string
  updated_at: string
}

export interface GroupInfo {
  name: string
  count: number
}

export interface TagInfo {
  name: string
  count: number
}

export interface GroupsData {
  groups: GroupInfo[]
  tags: TagInfo[]
  total_notes: number
}

export interface DocumentItem {
  id: string
  title: string
}

export interface Clip {
  id: string
  document_id: string
  section_id: string | null
  section_heading: string | null
  pdf_page_number: number | null
  selected_text: string
  user_note: string
  created_at: string
  updated_at: string
}

// Cluster suggestion types
export interface ClusterNotePreview {
  note_id: string
  excerpt: string
}

export interface ClusterSuggestion {
  id: string
  suggested_name: string
  note_ids: string[]
  note_count: number
  confidence_score: number
  status: string
  created_at: string
  previews: ClusterNotePreview[]
}

export interface CollectionTreeNode {
  id: string
  name: string
  children?: CollectionTreeNode[]
}

// Search response
export interface NoteSearchItem {
  note_id: string
  content: string
  tags: string[]
  group_name: string | null
  document_id: string | null
  score: number
  source: string
}

export interface NoteSearchResponse {
  query: string
  results: NoteSearchItem[]
  total: number
}

