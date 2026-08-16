import { apiGet, apiPost } from "@/lib/apiClient"

export interface LabTask {
  key: string
  label: string
  description: string
  typical_seconds: number
  /** Running this stage writes generated content into the library. */
  mutates_library: boolean
}

export interface LabCatalogue {
  tasks: LabTask[]
  qa_datasets: string[]
  installed_models: string[]
  registry_models: string[]
  current_model: string
  busy: boolean
  running_id: string | null
}

export interface LabTaskRun {
  task: string
  status: "pending" | "running" | "complete" | "failed"
  exit_code: number | null
  duration_s: number | null
  error: string | null
  /** The runner's own WARNING lines — a stage can skip rows and still report. */
  warnings: string[]
  /** Enough of a failure to diagnose it without going to a terminal. */
  stderr_tail: string[]
}

export interface LabArm {
  model: string
  tasks: LabTaskRun[]
  metrics: Record<string, number | string>
  failed_tasks: string[]
  environment: Record<string, unknown>
}

export interface LabMetricRow {
  key: string
  metric: string
  tier: "structural" | "quality" | "excluded" | "other"
  values: Record<string, number | null>
  /** Every arm reported the same value — the metric did not measure the model. */
  identical: boolean
}

export interface LabRun {
  id: string
  status: "running" | "complete" | "failed" | "cancelled"
  models: string[]
  tasks: string[]
  started_at: string
  finished_at: string | null
  total_units: number
  completed_units: number
  arms: LabArm[]
  rows: LabMetricRow[]
  separation: {
    separated: boolean
    separating_metrics: string[]
    unmeasured_tasks: string[]
  } | null
  error: string | null
  restore_error: string | null
}

export interface StartRunBody {
  models: string[]
  tasks: string[]
  qa_datasets: string[]
  max_questions: number
}

export const fetchLabCatalogue = (): Promise<LabCatalogue> =>
  apiGet<LabCatalogue>("/model-lab/catalogue")

export const fetchLabRuns = (): Promise<LabRun[]> => apiGet<LabRun[]>("/model-lab/runs")

export const fetchLabRun = (id: string): Promise<LabRun> =>
  apiGet<LabRun>(`/model-lab/runs/${id}`)

export const startLabRun = (body: StartRunBody): Promise<LabRun> =>
  apiPost<LabRun>("/model-lab/runs", body)

export const cancelLabRun = (id: string): Promise<{ cancelling: boolean }> =>
  apiPost<{ cancelling: boolean }>(`/model-lab/runs/${id}/cancel`, {})
