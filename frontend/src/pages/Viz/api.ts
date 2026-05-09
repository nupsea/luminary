// HTTP wrappers backing the Viz page. No React, no state. Each helper
// returns the parsed body (or throws); useQuery in Viz.tsx wires them
// up.

import { API_BASE } from "@/lib/config"

import type {
  DocListItem,
  GraphData,
  LearningPathData,
  MasteryConceptsResponse,
  TagGraphData,
} from "./types"

export async function fetchTagGraph(): Promise<TagGraphData> {
  const res = await fetch(`${API_BASE}/tags/graph`)
  if (!res.ok) throw new Error("Failed to fetch tag graph")
  return res.json() as Promise<TagGraphData>
}

export async function fetchMasteryConcepts(
  docIds: string[],
): Promise<MasteryConceptsResponse> {
  const params = docIds.map((id) => `document_ids=${encodeURIComponent(id)}`).join("&")
  const res = await fetch(`${API_BASE}/mastery/concepts?${params}`)
  if (!res.ok) return { document_ids: docIds, concepts: [] }
  return res.json() as Promise<MasteryConceptsResponse>
}

export async function fetchGraphData(
  documentId: string | null,
  scope: "document" | "all",
  viewMode: "knowledge_graph" | "call_graph",
  showCrossBook: boolean = false,
  includeNotes: boolean = false,
): Promise<GraphData> {
  const url =
    scope === "document" && documentId
      ? `${API_BASE}/graph/${documentId}?type=${viewMode}&include_notes=${includeNotes}`
      : `${API_BASE}/graph?doc_ids=&include_same_concept=${showCrossBook}&include_notes=${includeNotes}`
  const res = await fetch(url)
  if (!res.ok) throw new Error("Failed to fetch graph data")
  return res.json() as Promise<GraphData>
}

export async function fetchLearningPath(
  documentId: string,
  startEntity: string,
): Promise<LearningPathData> {
  const url = `${API_BASE}/graph/learning-path?document_id=${encodeURIComponent(documentId)}&start_entity=${encodeURIComponent(startEntity)}`
  const res = await fetch(url)
  if (!res.ok) throw new Error("Failed to fetch learning path")
  return res.json() as Promise<LearningPathData>
}

export async function fetchDocList(): Promise<DocListItem[]> {
  const res = await fetch(`${API_BASE}/documents?sort=newest&page=1&page_size=100`)
  if (!res.ok) return []
  const data = (await res.json()) as { items: DocListItem[] }
  return data.items ?? []
}
