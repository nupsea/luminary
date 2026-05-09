// Centralised colour + node-set constants for the Viz page.
//
// Sigma.js does not natively support dashed/dotted edges without a
// custom edge program, so we differentiate edge categories
// (PREREQUISITE_OF, SAME_CONCEPT, WRITTEN_ABOUT, LINKS_TO, learning
// path) purely by colour + weight.

import type { EntityType } from "@/lib/vizUtils"

export const BLIND_SPOT_COLOR = "#94a3b8" // slate-400: no flashcards

/** Diagram-derived node types that use the hexagon renderer (S136). */
export const DIAGRAM_NODE_TYPES: ReadonlySet<string> = new Set([
  "COMPONENT",
  "ACTOR",
  "ENTITY_DM",
  "STEP",
])

export const TYPE_COLORS: Record<EntityType, string> = {
  PERSON: "#3b82f6",
  ORGANIZATION: "#8b5cf6",
  PLACE: "#10b981",
  CONCEPT: "#f59e0b",
  EVENT: "#ef4444",
  TECHNOLOGY: "#06b6d4",
  DATE: "#6b7280",
  // Tech-specific types (S135)
  LIBRARY: "#0ea5e9",
  DESIGN_PATTERN: "#d946ef",
  ALGORITHM: "#f97316",
  DATA_STRUCTURE: "#84cc16",
  PROTOCOL: "#a78bfa",
  API_ENDPOINT: "#fb7185",
  // Diagram-derived types (S136)
  COMPONENT: "#14b8a6", // teal-500
  ACTOR: "#f43f5e", // rose-500
  ENTITY_DM: "#a3e635", // lime-400
  STEP: "#fbbf24", // amber-400
}

export const DEFAULT_COLOR = "#94a3b8"
export const DIM_COLOR = "rgba(200,200,200,0.15)"

// PREREQUISITE_OF edges (S139)
export const PREREQ_EDGE_COLOR = "#a855f7" // purple-500

// SAME_CONCEPT edge colours (S141)
export const SAME_CONCEPT_COLOR = "#94a3b8" // slate-400 -- no contradiction
export const SAME_CONCEPT_CONTRADICTION_COLOR = "#ef4444" // red-500 -- contradiction detected

// Note node edge colours (S172)
export const WRITTEN_ABOUT_EDGE_COLOR = "#94a3b8" // slate-400 -- thin grey lines
export const LINKS_TO_EDGE_COLOR = "#6366f1" // indigo-500 -- note-to-note
// NOTE_NODE_COLOR is imported from @/lib/noteGraphUtils

// Learning path edges (S117)
export const LP_EDGE_COLOR = "#f97316" // orange-500
