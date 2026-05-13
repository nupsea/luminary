// HTTP wrappers backing the Learning page. Pure functions; the page and
// its sub-components wire them up via tanstack-query useQuery / useMutation.

import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/apiClient"
import type {
  DocumentListItem,
  DocumentListResponse,
  SortOption,
} from "@/components/library/types"

import type {
  DocumentGroup,
  DueCountResponse,
  SessionListResponse,
  StartConceptsData,
} from "./types"

export async function fetchSearch(
  q: string,
  contentTypes: string,
): Promise<DocumentGroup[]> {
  try {
    const data = await apiGet<{ results: DocumentGroup[] }>("/search", {
      q,
      limit: 30,
      content_types: contentTypes || undefined,
    })
    return data.results
  } catch {
    return []
  }
}

export const fetchDocuments = (params: {
  content_type?: string
  tag?: string
  sort: SortOption
  page: number
  page_size: number
}): Promise<DocumentListResponse> =>
  apiGet<DocumentListResponse>("/documents", {
    sort: params.sort,
    page: params.page,
    page_size: params.page_size,
    content_type: params.content_type,
    tag: params.tag,
  })

export async function fetchRecentlyAccessed(): Promise<DocumentListItem[]> {
  try {
    const data = await apiGet<DocumentListResponse>("/documents", {
      sort: "last_accessed",
      page_size: 5,
    })
    return data.items
  } catch {
    return []
  }
}

export const patchTags = (id: string, tags: string[]): Promise<void> =>
  apiPatch(`/documents/${id}/tags`, { tags })

export const bulkDelete = (ids: string[]): Promise<void> =>
  apiPost("/documents/bulk-delete", { ids })

export const deleteDocument = (id: string): Promise<void> =>
  apiDelete(`/documents/${id}`)

export const fetchDueCount = (): Promise<DueCountResponse> =>
  apiGet<DueCountResponse>("/study/due-count")

export const fetchRecentSessions = (): Promise<SessionListResponse> =>
  apiGet<SessionListResponse>("/study/sessions", { page_size: 20 })

export async function fetchNotesCount(): Promise<number> {
  try {
    const data = await apiGet<unknown[]>("/notes")
    return data.length
  } catch {
    return 0
  }
}

export const fetchStartConcepts = (
  documentId: string,
): Promise<StartConceptsData> =>
  apiGet<StartConceptsData>("/study/start", { document_id: documentId })
