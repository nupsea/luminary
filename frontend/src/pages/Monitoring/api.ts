// HTTP wrappers backing the Monitoring page. All throw on non-ok so
// the section's catch handler can flip its error: true flag (each
// section tracks its own envelope rather than blanking the whole
// page on a single failure).

import { apiGet, apiPost } from "@/lib/apiClient"

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

export const fetchOverview = (): Promise<MonitoringOverview> =>
  apiGet<MonitoringOverview>("/monitoring/overview")

export const fetchTraces = (): Promise<TracesResponse> =>
  apiGet<TracesResponse>("/monitoring/traces")

export const fetchEvalRuns = (): Promise<EvalRun[]> =>
  apiGet<EvalRun[]>("/monitoring/evals")

export const fetchModelUsage = (): Promise<ModelUsageItem[]> =>
  apiGet<ModelUsageItem[]>("/monitoring/model-usage")

export const fetchLLMSettings = (): Promise<LLMSettings> =>
  apiGet<LLMSettings>("/settings/llm")

export async function fetchDocuments(): Promise<Document[]> {
  const data = await apiGet<{ items?: Document[] } | Document[]>("/documents")
  // handle both paginated and legacy list responses
  if (Array.isArray(data)) return data
  return (data as { items?: Document[] }).items ?? []
}

export const fetchEvalHistory = (): Promise<EvalHistoryItem[]> =>
  apiGet<EvalHistoryItem[]>("/monitoring/eval-history")

export const fetchPhoenixUrl = (): Promise<PhoenixUrl> =>
  apiGet<PhoenixUrl>("/monitoring/phoenix-url")

export const fetchEvalResults = (): Promise<EvalResultItem[]> =>
  apiGet<EvalResultItem[]>("/evals/results")

export const fetchEvalDatasets = (): Promise<string[]> =>
  apiGet<string[]>("/evals/datasets")

export const triggerEvalRun = (dataset: string): Promise<void> =>
  apiPost<void>("/evals/run", { dataset })

export function fetchMasteryConcepts(
  documentIds: string[],
): Promise<MasteryConceptsResponse> {
  const url = new URL("https://placeholder/mastery/concepts")
  documentIds.forEach((id) => url.searchParams.append("document_ids", id))
  return apiGet<MasteryConceptsResponse>(
    `/mastery/concepts?${url.searchParams.toString()}`,
  )
}

export const fetchMasteryHeatmap = (
  documentId: string,
): Promise<MasteryHeatmapResponse> =>
  apiGet<MasteryHeatmapResponse>("/mastery/heatmap", { document_id: documentId })
