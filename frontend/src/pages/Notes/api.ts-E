// HTTP wrappers backing the Notes page. Pure functions; useQuery /
// useMutation in Notes.tsx + its sub-components wire them up.

import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/apiClient"
import type { NamingViolation } from "@/components/OrganizationPlanDialog"

import type {
  Clip,
  ClusterSuggestion,
  DocumentItem,
  GroupsData,
  Note,
  NoteSearchResponse,
} from "./types"

export const fetchNotes = (
  documentId?: string,
  group?: string,
  tag?: string,
  collectionId?: string,
): Promise<Note[]> =>
  apiGet<Note[]>("/notes", {
    document_id: documentId,
    group,
    tag,
    collection_id: collectionId,
  })

export async function fetchGroups(): Promise<GroupsData> {
  try {
    return await apiGet<GroupsData>("/notes/groups")
  } catch {
    return { groups: [], tags: [], total_notes: 0 }
  }
}

export async function fetchDocumentList(): Promise<DocumentItem[]> {
  try {
    const data = await apiGet<{ items?: DocumentItem[] } | DocumentItem[]>(
      "/documents",
      { page_size: 200 },
    )
    return Array.isArray(data) ? data : (data.items ?? [])
  } catch {
    return []
  }
}

export const deleteNote = (id: string): Promise<void> =>
  apiDelete(`/notes/${id}`)

export const fetchClips = (documentId?: string): Promise<Clip[]> =>
  apiGet<Clip[]>("/clips", { document_id: documentId })

export const patchClipNote = (id: string, userNote: string): Promise<Clip> =>
  apiPatch<Clip>(`/clips/${id}`, { user_note: userNote })

export const deleteClip = (id: string): Promise<void> =>
  apiDelete(`/clips/${id}`)

export const createNoteFromClip = (
  clip: Clip,
  docTitle: string,
): Promise<{ id: string }> => {
  const body = `> ${clip.selected_text}\n\n*Source: ${docTitle}${clip.section_heading ? ` — ${clip.section_heading}` : ""}*`
  return apiPost<{ id: string }>("/notes", {
    content: body,
    tags: ["clip"],
    document_id: clip.document_id,
    section_id: clip.section_id ?? null,
  })
}

export const fetchClusterSuggestions = (): Promise<ClusterSuggestion[]> =>
  apiGet<ClusterSuggestion[]>("/notes/cluster/suggestions")

export const postCluster = (): Promise<{
  queued?: boolean
  cached?: boolean
  total_notes?: number
  last_run?: string
}> => apiPost("/notes/cluster")

export const fetchNamingViolations = (): Promise<NamingViolation[]> =>
  apiPost<NamingViolation[]>("/notes/cluster/normalize-check")

export const fetchNoteSearch = (q: string, k = 10): Promise<NoteSearchResponse> =>
  apiGet<NoteSearchResponse>("/notes/search", { q, k })
