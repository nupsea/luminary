// Pure HTTP wrappers backing the Study page. No React, no state -- just
// fetch + types. Each helper returns the parsed body (or throws); the
// callers are useQuery / useMutation in pages/Study.tsx and its
// sub-components.
//
// New helpers should land here, not back in pages/Study.tsx.

import { API_BASE } from "@/lib/config"
import { buildSearchParams } from "@/lib/studyUtils"
import type { FlashcardSearchFilters } from "@/lib/studyUtils"

import type {
  DocListItem,
  DocumentSections,
  Flashcard,
  FlashcardSearchResponse,
} from "./types"

export async function fetchDocList(): Promise<DocListItem[]> {
  const res = await fetch(`${API_BASE}/documents?sort=newest&page=1&page_size=100`)
  if (!res.ok) return []
  const data = (await res.json()) as { items: DocListItem[] }
  return data.items ?? []
}

export async function fetchFlashcardSearch(
  filters: FlashcardSearchFilters,
): Promise<FlashcardSearchResponse> {
  const params = buildSearchParams(filters)
  const query = params.toString()
  const res = await fetch(`${API_BASE}/flashcards/search${query ? `?${query}` : ""}`)
  if (!res.ok) return { items: [], total: 0, page: 1, page_size: 20 }
  return res.json() as Promise<FlashcardSearchResponse>
}

export async function fetchDocumentSections(documentId: string): Promise<DocumentSections> {
  const res = await fetch(`${API_BASE}/documents/${documentId}`)
  if (!res.ok) return { sections: [] }
  return res.json() as Promise<DocumentSections>
}

// `any` matches the original inline shape; tightening to a proper Stats
// type is a separate concern (the response is large + evolving).
export async function fetchStudyStats(documentId: string): Promise<any> {
  const res = await fetch(`${API_BASE}/study/stats/${documentId}`)
  if (!res.ok) throw new Error("Failed to load study stats")
  return res.json()
}

/** Throws on POST /generate failure so the caller can read `.status`
    and surface a "rate limit" / "LLM unavailable" message distinct
    from a generic toast. */
export class GenerateError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function generateFlashcards(req: {
  document_id: string
  scope: "full" | "section"
  section_heading: string | null
  count: number
  difficulty: "easy" | "medium" | "hard"
}): Promise<Flashcard[]> {
  const res = await fetch(`${API_BASE}/flashcards/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  })
  if (!res.ok) throw new GenerateError(res.status, "Failed to generate flashcards")
  return res.json() as Promise<Flashcard[]>
}

export async function generateTechnicalFlashcards(req: {
  document_id: string
  scope: "full" | "section"
  section_heading: string | null
  count: number
}): Promise<Flashcard[]> {
  const res = await fetch(`${API_BASE}/flashcards/generate-technical`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  })
  if (!res.ok) throw new GenerateError(res.status, "Failed to generate technical flashcards")
  return res.json() as Promise<Flashcard[]>
}

export async function updateFlashcard(
  id: string,
  data: { question?: string; answer?: string },
): Promise<Flashcard> {
  const res = await fetch(`${API_BASE}/flashcards/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error("Failed to update flashcard")
  return res.json() as Promise<Flashcard>
}

export async function deleteFlashcard(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/flashcards/${id}`, { method: "DELETE" })
  if (!res.ok) throw new Error("Failed to delete flashcard")
}

export async function bulkDeleteFlashcards(ids: string[]): Promise<{ deleted: number }> {
  const res = await fetch(`${API_BASE}/flashcards/bulk-delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  })
  if (!res.ok) throw new Error("Failed to delete selected flashcards")
  return res.json() as Promise<{ deleted: number }>
}

export async function deleteAllFlashcardsForDocument(documentId: string): Promise<void> {
  const res = await fetch(
    `${API_BASE}/flashcards/document/${encodeURIComponent(documentId)}`,
    { method: "DELETE" },
  )
  if (!res.ok) throw new Error("Failed to delete all flashcards")
}

export async function generateFlashcardsFromGraph(
  documentId: string,
  k: number,
): Promise<Flashcard[]> {
  const res = await fetch(`${API_BASE}/flashcards/generate-from-graph`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document_id: documentId, k }),
  })
  if (!res.ok) throw new GenerateError(res.status, "Failed to generate graph flashcards")
  return res.json() as Promise<Flashcard[]>
}

export async function generateClozeFlashcards(
  sectionId: string,
  count: number,
): Promise<Flashcard[]> {
  const res = await fetch(
    `${API_BASE}/flashcards/cloze/${encodeURIComponent(sectionId)}?count=${count}`,
    { method: "POST" },
  )
  if (!res.ok) throw new GenerateError(res.status, "Failed to generate cloze flashcards")
  return res.json() as Promise<Flashcard[]>
}
