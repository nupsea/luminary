export type DatasetStatus = "pending" | "generating" | "complete" | "failed"
export type DatasetSize = "small" | "medium" | "large"

export interface EvalRunSummary {
  id?: string
  run_at: string
  model_used: string
  hit_rate_5: number | null
  mrr: number | null
  faithfulness: number | null
  answer_relevance?: number | null
  context_precision?: number | null
  context_recall?: number | null
  eval_kind?: string | null
}

export interface GoldenDataset {
  id: string | null
  name: string
  description: string | null
  size: DatasetSize | null
  generator_model: string | null
  source_document_ids: string[]
  status: DatasetStatus | "complete"
  generated_count: number
  target_count: number
  created_at: string | null
  completed_at: string | null
  error_message: string | null
  last_run: EvalRunSummary | null
  source: "db" | "file"
}

export interface GoldenQuestion {
  id: string
  question: string
  ground_truth_answer: string
  context_hint: string
  source_chunk_id: string
  source_document_id: string
  quality_score: number
  included: boolean
}

export interface GoldenDatasetDetail extends GoldenDataset {
  questions: GoldenQuestion[]
  offset: number
  limit: number
}

export interface DocumentOption {
  id: string
  title: string
  content_type: string
  stage: string
}

export interface EvalRunFull {
  id: string
  dataset_name: string
  run_at: string
  hit_rate_5: number | null
  mrr: number | null
  faithfulness: number | null
  answer_relevance: number | null
  routing_accuracy: number | null
  per_route: Record<string, unknown> | null
  ablation_metrics: Record<string, unknown> | null
  eval_kind: string | null
  model_used: string
  citation_support_rate: number | null
}

export interface FileQuestion {
  q: string
  a: string
  context_hint: string | null
  source_file: string | null
}

export interface EvalRegressionItem {
  dataset: string
  metric: string
  current_value: number
  baseline_value: number
  drop_pct: number
  eval_kind: string | null
}
