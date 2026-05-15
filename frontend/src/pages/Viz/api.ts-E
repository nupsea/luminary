// HTTP wrappers backing the Viz page. No React, no state. Each helper
// returns the parsed body (or throws); useQuery in Viz.tsx wires them
// up.

import { apiGet } from "@/lib/apiClient"

import type {
  DocListItem,
  GraphData,
  LearningPathData,
  MasteryConceptsResponse,
  TagGraphData,
} from "./types"

export const fetchTagGraph = (): Promise<TagGraphData> =>
  apiGet<TagGraphData>("/tags/graph")

export async function fetchMasteryConcepts(
  docIds: string[],
): Promise<MasteryConceptsResponse> {
  const url = new URL("https://placeholder/mastery/concepts")
  docIds.forEach((id) => url.searchParams.append("document_ids", id))
  try {
    return await apiGet<MasteryConceptsResponse>(
      `/mastery/concepts?${url.searchParams.toString()}`,
    )
  } catch {
    return { document_ids: docIds, concepts: [] }
  }
}

export const fetchGraphData = (
  documentId: string | null,
  scope: "document" | "all",
  viewMode: "knowledge_graph" | "call_graph",
  showCrossBook: boolean = false,
  includeNotes: boolean = false,
): Promise<GraphData> =>
  scope === "document" && documentId
    ? apiGet<GraphData>(`/graph/${documentId}`, {
        type: viewMode,
        include_notes: includeNotes,
      })
    : apiGet<GraphData>("/graph", {
        doc_ids: "",
        include_same_concept: showCrossBook,
        include_notes: includeNotes,
      })

export const fetchLearningPath = (
  documentId: string,
  startEntity: string,
): Promise<LearningPathData> =>
  apiGet<LearningPathData>("/graph/learning-path", {
    document_id: documentId,
    start_entity: startEntity,
  })

export async function fetchDocList(): Promise<DocListItem[]> {
  try {
    const data = await apiGet<{ items: DocListItem[] }>("/documents", {
      sort: "newest",
      page: 1,
      page_size: 100,
    })
    return data.items ?? []
  } catch {
    return []
  }
}
