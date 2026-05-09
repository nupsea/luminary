// Type interfaces consumed by Viz.tsx and its sub-modules.
//
// These mirror the FastAPI response shapes for the graph / learning
// path / tag graph / mastery overlay endpoints. As the audit-#15
// codegen migration spreads, prefer
//   `import type { components } from "@/types/api"`
//   `type GraphNode = components["schemas"]["GraphNode"]`
// over the handwritten interfaces below.

import type { TagEdgeData, TagNodeData } from "@/components/TagGraph"

// Learning path types (S117)
export interface LearningPathNode {
  entity_id: string
  name: string
  entity_type: string
  depth: number
}

export interface LearningPathEdge {
  from_entity: string
  to_entity: string
  confidence: number
}

export interface LearningPathData {
  start_entity: string
  document_id: string
  nodes: LearningPathNode[]
  edges: LearningPathEdge[]
}

// Tag graph types (S167)
export interface TagGraphData {
  nodes: TagNodeData[]
  edges: TagEdgeData[]
  generated_at: number
}

// Mastery / retention overlay types
export interface MasteryConceptItem {
  concept: string
  mastery: number
  card_count: number
  due_soon: number
  no_flashcards: boolean
  document_ids: string[]
}

export interface MasteryConceptsResponse {
  document_ids: string[]
  concepts: MasteryConceptItem[]
}

// Core graph types
export interface GraphNode {
  id: string
  label: string
  type: string
  size: number
  source_image_id?: string // set for diagram-derived nodes (S136)
  note_id?: string // set for Note nodes (S172)
  outgoing_link_count?: number // set for Note nodes (S172)
}

export interface GraphEdge {
  source: string
  target: string
  weight: number
  relation?: string // e.g. "PREREQUISITE_OF", "CO_OCCURS", "IMPLEMENTS", "SAME_CONCEPT"
  contradiction?: boolean // true when SAME_CONCEPT edge has detected contradiction (S141)
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface SelectedNodeInfo {
  id: string
  label: string
  type: string
  frequency: number
  screenX: number
  screenY: number
  source_image_id?: string // set for diagram-derived nodes (S136)
}

export interface DocListItem {
  id: string
  title: string
  format?: string
  stage: string
}
