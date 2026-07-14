import { apiGet } from "@/lib/apiClient"
import type { GoldenDataset } from "./types"

// Judge-model helpers for the run console: which judges exist and which count
// as external.
export interface EvalModels {
  local: string[]
  frontier: string[]
}

export const fetchEvalModels = () => apiGet<EvalModels>("/evals/models")

export function judgeOptionsFrom(
  models: EvalModels | undefined,
  noneLabel: string,
): { value: string; label: string }[] {
  return [
    { value: "", label: noneLabel },
    ...(models?.local ?? []).map((m) => ({ value: m, label: `Local: ${m}` })),
    ...(models?.frontier ?? []).map((m) => ({ value: m, label: `Frontier: ${m}` })),
  ]
}

export const isExternalJudge = (model: string): boolean =>
  /^(openai|anthropic|gemini)\//.test(model)

// One selection shape for the run console + results dashboard: file goldens
// are keyed by name (run_eval --dataset), generated datasets by id
// (run_eval --dataset-id; their eval_runs rows store the id as dataset_name).
export interface DatasetSelection {
  key: string
  name: string
  source: "file" | "db"
}

export function toSelection(dataset: GoldenDataset): DatasetSelection | null {
  if (dataset.source === "file") {
    return { key: dataset.name, name: dataset.name, source: "file" }
  }
  if (!dataset.id) return null
  return { key: dataset.id, name: dataset.name, source: "db" }
}

// Surface the backend's `detail` (e.g. the dead-source-document 409 with its
// re-link guidance) instead of a generic failure string.
export async function errorFromResponse(res: Response, fallback: string): Promise<Error> {
  try {
    const body = (await res.json()) as { detail?: unknown }
    if (typeof body.detail === "string" && body.detail) return new Error(body.detail)
  } catch {
    // non-JSON body — fall through
  }
  return new Error(fallback)
}
