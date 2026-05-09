// HTTP wrappers backing the Notes page. Pure functions; useQuery /
// useMutation in Notes.tsx + its sub-components wire them up.

import { API_BASE } from "@/lib/config"
import type { NamingViolation } from "@/components/OrganizationPlanDialog"

import type {
  Clip,
  ClusterSuggestion,
  DocumentItem,
  GroupsData,
  Note,
  NoteSearchResponse,
} from "./types"

export async function fetchNotes(
  documentId?: string,
  group?: string,
  tag?: string,
  collectionId?: string,
): Promise<Note[]> {
  const params = new URLSearchParams()
  if (documentId) params.set("document_id", documentId)
  if (group) params.set("group", group)
  if (tag) params.set("tag", tag)
  if (collectionId) params.set("collection_id", collectionId)
  const res = await fetch(`${API_BASE}/notes?${params.toString()}`)
  if (!res.ok) throw new Error(`GET /notes failed: ${res.status}`)
  return res.json() as Promise<Note[]>
}

export async function fetchGroups(): Promise<GroupsData> {
  const res = await fetch(`${API_BASE}/notes/groups`)
  if (!res.ok) return { groups: [], tags: [], total_notes: 0 }
  return res.json() as Promise<GroupsData>
}

export async function fetchDocumentList(): Promise<DocumentItem[]> {
  const res = await fetch(`${API_BASE}/documents?page_size=200`)
  if (!res.ok) return []
  const data = (await res.json()) as { items?: DocumentItem[] } | DocumentItem[]
  return Array.isArray(data) ? data : (data.items ?? [])
}

export async function deleteNote(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/notes/${id}`, { method: "DELETE" })
  if (!res.ok && res.status !== 204)
    throw new Error(`DELETE /notes/${id} failed: ${res.status}`)
}

export async function fetchClips(documentId?: string): Promise<Clip[]> {
  const params = new URLSearchParams()
  if (documentId) params.set("document_id", documentId)
  const res = await fetch(`${API_BASE}/clips?${params.toString()}`)
  if (!res.ok) throw new Error(`GET /clips failed: ${res.status}`)
  return res.json() as Promise<Clip[]>
}

export async function patchClipNote(id: string, userNote: string): Promise<Clip> {
  const res = await fetch(`${API_BASE}/clips/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_note: userNote }),
  })
  if (!res.ok) throw new Error(`PATCH /clips/${id} failed: ${res.status}`)
  return res.json() as Promise<Clip>
}

export async function deleteClip(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/clips/${id}`, { method: "DELETE" })
  if (!res.ok && res.status !== 204)
    throw new Error(`DELETE /clips/${id} failed: ${res.status}`)
}

export async function createNoteFromClip(
  clip: Clip,
  docTitle: string,
): Promise<{ id: string }> {
  const body = `> ${clip.selected_text}\n\n*Source: ${docTitle}${clip.section_heading ? ` — ${clip.section_heading}` : ""}*`
  const res = await fetch(`${API_BASE}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      content: body,
      tags: ["clip"],
      document_id: clip.document_id,
      section_id: clip.section_id ?? null,
    }),
  })
  if (!res.ok) throw new Error(`POST /notes failed: ${res.status}`)
  return res.json() as Promise<{ id: string }>
}

export async function fetchClusterSuggestions(): Promise<ClusterSuggestion[]> {
  const res = await fetch(`${API_BASE}/notes/cluster/suggestions`)
  if (!res.ok) throw new Error(`GET /notes/cluster/suggestions failed: ${res.status}`)
  return res.json() as Promise<ClusterSuggestion[]>
}

export async function postCluster(): Promise<{
  queued?: boolean
  cached?: boolean
  total_notes?: number
  last_run?: string
}> {
  const res = await fetch(`${API_BASE}/notes/cluster`, { method: "POST" })
  if (!res.ok) throw new Error(`POST /notes/cluster failed: ${res.status}`)
  return res.json()
}

export async function fetchNamingViolations(): Promise<NamingViolation[]> {
  const res = await fetch(`${API_BASE}/notes/cluster/normalize-check`, { method: "POST" })
  if (!res.ok)
    throw new Error(`POST /notes/cluster/normalize-check failed: ${res.status}`)
  return res.json() as Promise<NamingViolation[]>
}

export async function fetchNoteSearch(q: string, k = 10): Promise<NoteSearchResponse> {
  const params = new URLSearchParams({ q, k: String(k) })
  const res = await fetch(`${API_BASE}/notes/search?${params.toString()}`)
  if (!res.ok) throw new Error(`GET /notes/search failed: ${res.status}`)
  return res.json() as Promise<NoteSearchResponse>
}
