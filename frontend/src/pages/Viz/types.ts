// Type interfaces consumed by Viz.tsx and its sub-modules.
// API shapes prefer generated `src/types/api.ts`; types
// without OpenAPI coverage or with a different UI shape stay inline.

import type { components } from "@/types/api"
import type { TagEdgeData, TagNodeData } from "@/components/TagGraph"

// Tag graph types. Generated TagGraphResponse uses TagNodeItem /
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
  source_image_id?: string // set for diagram-derived nodes
  note_id?: string // set for Note nodes
  outgoing_link_count?: number // set for Note nodes
}

export interface GraphEdge {
  source: string
  target: string
  weight: number
  relation?: string // e.g. "PREREQUISITE_OF", "CO_OCCURS", "IMPLEMENTS", "SAME_CONCEPT"
  contradiction?: boolean // true when SAME_CONCEPT edge has detected contradiction
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
  source_image_id?: string // set for diagram-derived nodes
}

export interface DocListItem {
  id: string
  title: string
  format?: string
  stage: string
}
