// Type interfaces consumed by Monitoring.tsx and its sub-components.

export interface TraceItem {
  span_id: string
  trace_id: string
  operation_name: string
  start_time: string
  duration_ms: number
  status: string
  attributes: Record<string, unknown>
}

export interface TracesResponse {
  traces: TraceItem[]
  message?: string | null
}

export interface MonitoringOverview {
  llm_status: string
  phoenix_running: boolean
  langfuse_configured: boolean
  total_documents: number
  total_chunks: number
  qa_calls_today: number
  avg_latency_ms: number | null
}

export interface EvalRun {
  id: string
  dataset_name: string
  model_used: string
  run_at: string
  hit_rate_5: number | null
  mrr: number | null
  faithfulness: number | null
  answer_relevance: number | null
  context_precision: number | null
  context_recall: number | null
}

export interface ModelUsageItem {
  model: string
  call_count: number
  avg_latency_ms: number | null
}

export interface EvalHistoryItem {
  timestamp: string
  dataset: string
  model: string
  hr5: number | null
  mrr: number | null
  faithfulness: number | null
  passed: boolean
}

export interface LLMSettings {
  processing_mode: string
  active_model: string
}

export interface EvalResultItem {
  dataset: string
  run_at: string
  hit_rate_5: number | null
  mrr: number | null
  faithfulness: number | null
  context_precision: number | null
  context_recall: number | null
  answer_relevancy: number | null
  passed_thresholds: boolean | null
}

export interface PhoenixUrl {
  url: string
  enabled: boolean
}

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

// Mastery panel types
export interface ConceptMasteryItem {
  concept: string
  mastery: number
  card_count: number
  due_soon: number
  no_flashcards: boolean
  document_ids: string[]
}

export interface HeatmapCellItem {
  chapter: string
  concept: string
  mastery: number | null
  card_count: number
}

export interface MasteryConceptsResponse {
  document_ids: string[]
  concepts: ConceptMasteryItem[]
}

export interface MasteryHeatmapResponse {
  document_id: string
  chapters: string[]
  concepts: string[]
  cells: HeatmapCellItem[]
}
