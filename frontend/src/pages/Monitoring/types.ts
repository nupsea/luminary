// Type interfaces consumed by Monitoring.tsx and its sub-components.
// API shapes sourced from generated `src/types/api.ts`;
// UI-only shapes and 4-field doc subsets stay inline below.

import type { components } from "@/types/api"

export type TraceItem = components["schemas"]["TraceItem"]
export type TracesResponse = components["schemas"]["TracesResponse"]
export type MonitoringOverview = components["schemas"]["MonitoringOverview"]
export type MonitoringMetrics = components["schemas"]["MonitoringMetrics"]
export type QADailyCount = components["schemas"]["QADailyCount"]
export type EvalRun = components["schemas"]["EvalRunResponse"]
export type EvalHistoryItem = components["schemas"]["EvalHistoryItem"]
export type EvalResultItem = components["schemas"]["EvalResultItem"]
export type PhoenixUrl = components["schemas"]["PhoenixUrlResponse"]
export type ConceptMasteryItem = components["schemas"]["ConceptMasteryOut"]
export type HeatmapCellItem = components["schemas"]["HeatmapCellOut"]
export type MasteryConceptsResponse = components["schemas"]["MasteryConceptsOut"]
export type MasteryHeatmapResponse = components["schemas"]["MasteryHeatmapOut"]

// Local-only: the GET /settings/llm endpoint returns this shape (legacy
// processing_mode / active_model), distinct from the canonical
// LLMSettingsResponse (mode/provider/model) used elsewhere.
export interface LLMSettings {
  processing_mode: string
  active_model: string
  ollama_reachable?: boolean
}

// Local-only: 4-field subset of DocumentListItem for the document
// mini-table on this page.
export interface Document {
  id: string
  title: string
  stage: string
  content_type: string
}

// Per-section state -- each panel tracks its own loading/error envelope
// so a single failed query doesn't kill the whole page.
export interface SectionState<T> {
  loading: boolean
  data: T
  error: boolean
}

export function initSection<T>(data: T): SectionState<T> {
  return { loading: true, data, error: false }
}
