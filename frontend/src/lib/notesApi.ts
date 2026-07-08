import { apiDelete, apiGet, apiPatch, apiPost, request } from "@/lib/apiClient"
import type { CollectionTreeItem } from "@/lib/collectionUtils"
import type { components } from "@/types/api"

export type Note = components["schemas"]["NoteResponse"]
export type NoteLinkItem = components["schemas"]["NoteLinkItem"]
export type NoteLinksResponse = components["schemas"]["NoteLinksResponse"]

export interface CreateNotePayload {
  content: string
  tags: string[]
  document_id: string | null
  source_document_ids?: string[]
  /** Optional manual title; when set the note is flagged manual-title. */
  title?: string
}

export interface PatchNotePayload {
  content?: string
  tags?: string[]
  group_name?: string
  source_document_ids?: string[]
  /** Empty string clears to NULL; either way flips title_auto_generated=False. */
  title?: string
}

export type NoteAutocompleteItem = components["schemas"]["NoteAutocompleteItem"]

export const createNote = (payload: CreateNotePayload): Promise<Note> =>
  apiPost<Note>("/notes", payload)

export const getNote = (id: string): Promise<Note> => apiGet<Note>(`/notes/${id}`)

export async function fetchNoteAutocomplete(q: string): Promise<NoteAutocompleteItem[]> {
  try {
    return await apiGet<NoteAutocompleteItem[]>("/notes/autocomplete", { q })
  } catch {
    return []
  }
}

export const patchNote = (id: string, data: PatchNotePayload): Promise<Note> =>
  apiPatch<Note>(`/notes/${id}`, data)

export const deleteNote = (id: string): Promise<void> =>
  apiDelete(`/notes/${id}`)

export async function fetchSuggestedTags(
  id: string,
  signal?: AbortSignal,
): Promise<string[]> {
  try {
    const data = await request<{ tags: string[] }>(
      `/notes/${id}/suggest-tags`,
      { method: "POST", signal },
    )
    return data.tags ?? []
  } catch {
    return []
  }
}

export async function suggestNoteTitle(content: string): Promise<string> {
  const data = await apiPost<{ title: string }>("/notes/suggest-title", { content })
  return data.title
}

/** Trigger background (re)generation of card summaries. `force` refreshes every
 *  note; otherwise only notes missing a description. Returns the queued count. */
export async function backfillNoteDescriptions(force = false): Promise<{ queued: number }> {
  return apiPost<{ queued: number }>(`/notes/descriptions/backfill?force=${force}`, {})
}

export async function fetchCollectionTree(
  contains?: "document" | "note",
): Promise<CollectionTreeItem[]> {
  try {
    const params = contains ? { contains } : undefined
    return await apiGet<CollectionTreeItem[]>("/collections/tree", params)
  } catch {
    return []
  }
}

export const addNoteToCollection = (
  collectionId: string,
  noteId: string,
): Promise<void> =>
  apiPost(`/collections/${collectionId}/members`, {
    member_ids: [noteId],
    member_type: "note",
  })

export const removeNoteFromCollection = (
  collectionId: string,
  noteId: string,
): Promise<void> =>
  apiDelete(`/collections/${collectionId}/members/${noteId}?member_type=note`)

export const addDocumentToCollection = (
  collectionId: string,
  documentId: string,
): Promise<void> =>
  apiPost(`/collections/${collectionId}/members`, {
    member_ids: [documentId],
    member_type: "document",
  })

export const removeDocumentFromCollection = (
  collectionId: string,
  documentId: string,
): Promise<void> =>
  apiDelete(`/collections/${collectionId}/members/${documentId}?member_type=document`)

export async function fetchNoteLinks(noteId: string): Promise<NoteLinksResponse> {
  try {
    return await apiGet<NoteLinksResponse>(`/notes/${noteId}/links`)
  } catch {
    return { outgoing: [], incoming: [] }
  }
}

export const createNoteLink = (
  noteId: string,
  targetNoteId: string,
  linkType: string,
): Promise<NoteLinkItem> =>
  apiPost<NoteLinkItem>(`/notes/${noteId}/links`, {
    target_note_id: targetNoteId,
    link_type: linkType,
  })

export const deleteNoteLink = (
  noteId: string,
  targetNoteId: string,
  linkType: string,
): Promise<void> =>
  apiDelete(
    `/notes/${noteId}/links/${targetNoteId}?link_type=${encodeURIComponent(linkType)}`,
  )
