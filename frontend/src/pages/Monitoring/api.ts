// HTTP wrappers backing the Monitoring page. All throw on non-ok so
// the section's catch handler can flip its error: true flag (each
// section tracks its own envelope rather than blanking the whole
// page on a single failure).

import { API_BASE } from "@/lib/config"

import type {
  Document,
  EvalHistoryItem,
  EvalResultItem,
  EvalRun,
  LLMSettings,
  MasteryConceptsResponse,
  MasteryHeatmapResponse,
  ModelUsageItem,
  MonitoringOverview,
  PhoenixUrl,
  TracesResponse,
} from "./types"

export async function fetchOverview(): Promise<MonitoringOverview> {
  const res = await fetch(`${API_BASE}/monitoring/overview`)
  if (!res.ok) throw new Error("overview failed")
  return res.json() as Promise<MonitoringOverview>
}

export async function fetchTraces(): Promise<TracesResponse> {
  const res = await fetch(`${API_BASE}/monitoring/traces`)
  if (!res.ok) throw new Error("traces failed")
  return res.json() as Promise<TracesResponse>
}

export async function fetchEvalRuns(): Promise<EvalRun[]> {
  const res = await fetch(`${API_BASE}/monitoring/evals`)
  if (!res.ok) throw new Error("evals failed")
  return res.json() as Promise<EvalRun[]>
}

export async function fetchModelUsage(): Promise<ModelUsageItem[]> {
  const res = await fetch(`${API_BASE}/monitoring/model-usage`)
  if (!res.ok) throw new Error("model-usage failed")
  return res.json() as Promise<ModelUsageItem[]>
}

export async function fetchLLMSettings(): Promise<LLMSettings> {
  const res = await fetch(`${API_BASE}/settings/llm`)
  if (!res.ok) throw new Error("llm-settings failed")
  return res.json() as Promise<LLMSettings>
}

export async function fetchDocuments(): Promise<Document[]> {
  const res = await fetch(`${API_BASE}/documents`)
  if (!res.ok) throw new Error("documents failed")
  const data = (await res.json()) as { items?: Document[] } | Document[]
  // handle both paginated and legacy list responses
  if (Array.isArray(data)) return data
  return (data as { items?: Document[] }).items ?? []
}

export async function fetchEvalHistory(): Promise<EvalHistoryItem[]> {
  const res = await fetch(`${API_BASE}/monitoring/eval-history`)
  if (!res.ok) throw new Error("eval-history failed")
  return res.json() as Promise<EvalHistoryItem[]>
}

export async function fetchPhoenixUrl(): Promise<PhoenixUrl> {
  const res = await fetch(`${API_BASE}/monitoring/phoenix-url`)
  if (!res.ok) throw new Error("phoenix-url failed")
  return res.json() as Promise<PhoenixUrl>
}

export async function fetchEvalResults(): Promise<EvalResultItem[]> {
  const res = await fetch(`${API_BASE}/evals/results`)
  if (!res.ok) throw new Error("evals/results failed")
  return res.json() as Promise<EvalResultItem[]>
}

export async function fetchEvalDatasets(): Promise<string[]> {
  const res = await fetch(`${API_BASE}/evals/datasets`)
  if (!res.ok) throw new Error("evals/datasets failed")
  return res.json() as Promise<string[]>
}

export async function triggerEvalRun(dataset: string): Promise<void> {
  const res = await fetch(`${API_BASE}/evals/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dataset }),
  })
  if (!res.ok) throw new Error(`evals/run failed: ${res.status}`)
}

export async function fetchMasteryConcepts(
  documentIds: string[],
): Promise<MasteryConceptsResponse> {
  const params = new URLSearchParams()
  documentIds.forEach((id) => params.append("document_ids", id))
  const res = await fetch(`${API_BASE}/mastery/concepts?${params.toString()}`)
  if (!res.ok) throw new Error("mastery/concepts failed")
  return res.json() as Promise<MasteryConceptsResponse>
}

export async function fetchMasteryHeatmap(
  documentId: string,
): Promise<MasteryHeatmapResponse> {
  const res = await fetch(
    `${API_BASE}/mastery/heatmap?document_id=${encodeURIComponent(documentId)}`,
  )
  if (!res.ok) throw new Error("mastery/heatmap failed")
  return res.json() as Promise<MasteryHeatmapResponse>
}
