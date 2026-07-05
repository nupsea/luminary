import type { GoldenDataset } from "./types"

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
