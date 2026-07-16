// HTTP wrappers backing the Monitoring page. All throw on non-ok so
// the section's catch handler can flip its error: true flag (each
// section tracks its own envelope rather than blanking the whole
// page on a single failure).

import { apiGet } from "@/lib/apiClient"

import type {
  Document,
  LLMSettings,
  MasteryConceptsResponse,
  MasteryHeatmapResponse,
  MonitoringMetrics,
  MonitoringOverview,
  PhoenixUrl,
  TracesResponse,
} from "./types"

export const fetchOverview = (): Promise<MonitoringOverview> =>
  apiGet<MonitoringOverview>("/monitoring/overview")

export const fetchTraces = (): Promise<TracesResponse> =>
  apiGet<TracesResponse>("/monitoring/traces")

export const fetchMetrics = (): Promise<MonitoringMetrics> =>
  apiGet<MonitoringMetrics>("/monitoring/metrics")

export const fetchLLMSettings = (): Promise<LLMSettings> =>
  apiGet<LLMSettings>("/settings/llm")

export async function fetchDocuments(): Promise<Document[]> {
  const data = await apiGet<{ items?: Document[] } | Document[]>("/documents")
  // handle both paginated and legacy list responses
  if (Array.isArray(data)) return data
  return (data as { items?: Document[] }).items ?? []
}

export const fetchPhoenixUrl = (): Promise<PhoenixUrl> =>
  apiGet<PhoenixUrl>("/monitoring/phoenix-url")

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
