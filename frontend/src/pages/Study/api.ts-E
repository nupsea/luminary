// Pure HTTP wrappers backing the Study page. No React, no state -- just
// fetch + types. Each helper returns the parsed body (or throws); the
// callers are useQuery / useMutation in pages/Study.tsx and its
// sub-components.
//
// New helpers should land here, not back in pages/Study.tsx.

import {
  ApiError,
  apiDelete,
  apiGet,
  apiPost,
  apiPut,
} from "@/lib/apiClient"
import { buildSearchParams } from "@/lib/studyUtils"
import type { FlashcardSearchFilters } from "@/lib/studyUtils"

import type {
  DocListItem,
  DocumentSections,
  Flashcard,
  FlashcardSearchResponse,
} from "./types"

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

export async function fetchFlashcardSearch(
  filters: FlashcardSearchFilters,
): Promise<FlashcardSearchResponse> {
  const params = buildSearchParams(filters)
  const query = params.toString()
  try {
    return await apiGet<FlashcardSearchResponse>(
      `/flashcards/search${query ? `?${query}` : ""}`,
    )
  } catch {
    return { items: [], total: 0, page: 1, page_size: 20 }
  }
}

export async function fetchDocumentSections(
  documentId: string,
): Promise<DocumentSections> {
  try {
    return await apiGet<DocumentSections>(`/documents/${documentId}`)
  } catch {
    return { sections: [] }
  }
}

// `any` matches the original inline shape; tightening to a proper Stats
// type is a separate concern (the response is large + evolving).
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function fetchStudyStats(documentId: string): Promise<any> {
  try {
    return await apiGet(`/study/stats/${documentId}`)
  } catch {
    throw new Error("Failed to load study stats")
  }
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

function asGenerateError(err: unknown, message: string): never {
  if (err instanceof ApiError) throw new GenerateError(err.status, message)
  throw new GenerateError(0, message)
}

export async function generateFlashcards(req: {
  document_id: string
  scope: "full" | "section"
  section_heading: string | null
  count: number
  difficulty: "easy" | "medium" | "hard"
}): Promise<Flashcard[]> {
  try {
    return await apiPost<Flashcard[]>("/flashcards/generate", req)
  } catch (err) {
    asGenerateError(err, "Failed to generate flashcards")
  }
}

export async function generateTechnicalFlashcards(req: {
  document_id: string
  scope: "full" | "section"
  section_heading: string | null
  count: number
}): Promise<Flashcard[]> {
  try {
    return await apiPost<Flashcard[]>("/flashcards/generate-technical", req)
  } catch (err) {
    asGenerateError(err, "Failed to generate technical flashcards")
  }
}

export async function updateFlashcard(
  id: string,
  data: { question?: string; answer?: string },
): Promise<Flashcard> {
  try {
    return await apiPut<Flashcard>(`/flashcards/${id}`, data)
  } catch {
    throw new Error("Failed to update flashcard")
  }
}

export async function deleteFlashcard(id: string): Promise<void> {
  try {
    await apiDelete(`/flashcards/${id}`)
  } catch {
    throw new Error("Failed to delete flashcard")
  }
}

export async function bulkDeleteFlashcards(
  ids: string[],
): Promise<{ deleted: number }> {
  try {
    return await apiPost<{ deleted: number }>("/flashcards/bulk-delete", { ids })
  } catch {
    throw new Error("Failed to delete selected flashcards")
  }
}

export async function deleteAllFlashcardsForDocument(
  documentId: string,
): Promise<void> {
  try {
    await apiDelete(`/flashcards/document/${encodeURIComponent(documentId)}`)
  } catch {
    throw new Error("Failed to delete all flashcards")
  }
}

export async function generateFlashcardsFromGraph(
  documentId: string,
  k: number,
): Promise<Flashcard[]> {
  try {
    return await apiPost<Flashcard[]>("/flashcards/generate-from-graph", {
      document_id: documentId,
      k,
    })
  } catch (err) {
    asGenerateError(err, "Failed to generate graph flashcards")
  }
}

export async function generateClozeFlashcards(
  sectionId: string,
  count: number,
): Promise<Flashcard[]> {
  try {
    return await apiPost<Flashcard[]>(
      `/flashcards/cloze/${encodeURIComponent(sectionId)}?count=${count}`,
    )
  } catch (err) {
    asGenerateError(err, "Failed to generate cloze flashcards")
  }
}
