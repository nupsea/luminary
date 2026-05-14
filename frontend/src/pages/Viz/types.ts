// Type interfaces consumed by Viz.tsx and its sub-modules.
// API shapes prefer generated `src/types/api.ts` (audit #15); types
// without OpenAPI coverage or with a different UI shape stay inline.

import type { components } from "@/types/api"
import type { TagEdgeData, TagNodeData } from "@/components/TagGraph"

// Learning path types (S117). The generated LearningPathResponse types
// `edges` as `{[k: string]: unknown}[]` (loose dict) -- locally we keep
// the typed LearningPathEdge / LearningPathData so callers retain
// field-level type safety. Only LearningPathNode aliases cleanly.
export type LearningPathNode = components["schemas"]["LearningPathNode"]

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

// Tag graph types (S167). Generated TagGraphResponse uses TagNodeItem /
// TagEdgeItem; the Viz page renders via TagGraph component types which
// have a different shape, so keep local.
export interface TagGraphData {
  nodes: TagNodeData[]
  edges: TagEdgeData[]
  generated_at: number
}

// Mastery / retention overlay types
export type MasteryConceptItem = components["schemas"]["ConceptMasteryOut"]
export type MasteryConceptsResponse = components["schemas"]["MasteryConceptsOut"]

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
