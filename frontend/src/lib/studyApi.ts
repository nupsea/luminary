/**
 * Shared types and API functions for study sessions (Flashcard + Teach-back).
 *
 * Both FlashcardSession and TeachbackSession import from here to avoid duplication.
 */

import { API_BASE } from "@/lib/config"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Flashcard {
  id: string
  question: string
  answer: string
  source_excerpt: string
  due_date: string | null
  section_id: string | null
  flashcard_type: string | null
  cloze_text: string | null
}

export interface SourceContext {
  section_heading: string
  section_preview: string
  document_title: string
  pdf_page_number: number | null
  section_id: string
  document_id: string
}

export type Rating = "again" | "hard" | "good" | "easy"

export interface PendingTeachback {
  id: string
  flashcardId: string
  question: string
}

export interface TeachbackResultItem {
  id: string
  status: "pending" | "complete" | "error"
  flashcard_id: string
  question: string
  expected_answer?: string
  score: number | null
  correct_points: string[]
  missing_points: string[]
  misconceptions: string[]
  correction_flashcard_id: string | null
  rubric: {
    accuracy: { score: number; evidence: string }
    completeness: { score: number; missed_points: string[] }
    clarity: { score: number; evidence: string }
  } | null
  user_explanation?: string | null
}

export interface StudySessionItem {
  id: string
  started_at: string
  ended_at: string | null
  duration_minutes: number | null
  cards_reviewed: number
  cards_correct: number
  accuracy_pct: number | null
  document_id: string | null
  document_title: string | null
  collection_id: string | null
  collection_name: string | null
  mode: string
  has_pending_evaluations?: boolean
}

export interface SessionListResponse {
  items: StudySessionItem[]
  total: number
  page: number
  page_size: number
}

// ---------------------------------------------------------------------------
// API Functions
// ---------------------------------------------------------------------------

export async function startSession(
  documentId: string | null,
  mode: string = "flashcard",
  collectionId: string | null = null,
  plannedCardIds: string[] | null = null,
): Promise<string> {
  const res = await fetch(`${API_BASE}/study/sessions/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      document_id: documentId,
      collection_id: collectionId,
      mode,
      planned_card_ids: plannedCardIds,
    }),
  })
  if (!res.ok) throw new Error("Failed to start session")
  const data = (await res.json()) as { id: string }
  return data.id
}

export interface SessionRemainingState {
  answered_count: number
  planned_count: number
  cards: Flashcard[]
}

export async function fetchSessionRemainingCards(
  sessionId: string,
): Promise<SessionRemainingState> {
  const res = await fetch(
    `${API_BASE}/study/sessions/${encodeURIComponent(sessionId)}/remaining-cards`,
  )
  if (!res.ok) return { answered_count: 0, planned_count: 0, cards: [] }
  return res.json() as Promise<SessionRemainingState>
}

/** Most recent open session for this scope, or null if none. */
export async function fetchOpenSession(params: {
  mode: string
  documentId: string | null
  collectionId: string | null
}): Promise<{ id: string } | null> {
  const qs = new URLSearchParams({ mode: params.mode })
  if (params.documentId) qs.set("document_id", params.documentId)
  if (params.collectionId) qs.set("collection_id", params.collectionId)
  const res = await fetch(`${API_BASE}/study/sessions/open?${qs.toString()}`)
  if (res.status === 404) return null
  if (!res.ok) return null
  const data = (await res.json()) as { id: string }
  return { id: data.id }
}

export async function fetchDueCards(
  documentId: string | null,
  collectionId: string | null = null,
  filters: {
    tag?: string
    document_ids?: string[]
    note_ids?: string[]
    limit?: number
  } = {},
): Promise<Flashcard[]> {
  const params = new URLSearchParams({
    limit: String(filters.limit ?? 50),
  })
  if (documentId) params.set("document_id", documentId)
  if (collectionId) params.set("collection_id", collectionId)
  if (filters.tag) params.set("tag", filters.tag)
  if (filters.document_ids?.length) {
    filters.document_ids.forEach((id: string) => params.append("document_ids", id))
  }
  if (filters.note_ids?.length) {
    filters.note_ids.forEach((id: string) => params.append("note_ids", id))
  }
  const res = await fetch(`${API_BASE}/study/due?${params.toString()}`)
  if (!res.ok) return []
  return res.json() as Promise<Flashcard[]>
}

export async function submitReview(
  cardId: string,
  rating: Rating,
  sessionId: string,
): Promise<void> {
  await fetch(`${API_BASE}/flashcards/${cardId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rating, session_id: sessionId }),
  })
}

export async function endSession(sessionId: string): Promise<void> {
  await fetch(`${API_BASE}/study/sessions/${sessionId}/end`, { method: "POST" })
}

export async function reopenSession(sessionId: string): Promise<void> {
  await fetch(
    `${API_BASE}/study/sessions/${encodeURIComponent(sessionId)}/reopen`,
    { method: "POST" },
  )
}

export async function deleteStudySession(sessionId: string): Promise<void> {
  const res = await fetch(
    `${API_BASE}/study/sessions/${encodeURIComponent(sessionId)}`,
    { method: "DELETE" },
  )
  if (!res.ok) throw new Error("Failed to delete session")
}

export async function fetchSourceContext(
  cardId: string,
): Promise<SourceContext | null> {
  try {
    const res = await fetch(
      `${API_BASE}/flashcards/${encodeURIComponent(cardId)}/source-context`,
    )
    if (!res.ok) return null
    return res.json() as Promise<SourceContext>
  } catch {
    return null
  }
}

// ---------------------------------------------------------------------------
// Teach-back API
// ---------------------------------------------------------------------------

export async function submitTeachbackAsync(
  flashcardId: string,
  userExplanation: string,
  sessionId: string | null = null,
): Promise<{ id: string }> {
  const res = await fetch(`${API_BASE}/study/teachback/async`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      flashcard_id: flashcardId,
      user_explanation: userExplanation,
      session_id: sessionId,
    }),
  })
  if (!res.ok) throw new Error("Teachback submit failed")
  return res.json() as Promise<{ id: string }>
}

export async function fetchTeachbackResults(
  ids: string[],
): Promise<TeachbackResultItem[]> {
  if (ids.length === 0) return []
  const res = await fetch(`${API_BASE}/study/teachback/results?ids=${ids.join(",")}`)
  if (!res.ok) throw new Error("Failed to fetch teachback results")
  const data = (await res.json()) as { results: TeachbackResultItem[] }
  return data.results
}

export async function fetchSessionTeachbackResults(
  sessionId: string,
): Promise<TeachbackResultItem[]> {
  const res = await fetch(
    `${API_BASE}/study/sessions/${encodeURIComponent(sessionId)}/teachback-results`,
  )
  if (!res.ok) return []
  const data = (await res.json()) as { results: TeachbackResultItem[] }
  return data.results
}

// ---------------------------------------------------------------------------
// Session listing
// ---------------------------------------------------------------------------

export async function fetchSessions(
  page: number,
  pageSize: number,
  opts: {
    mode?: string
    status?: string
    collectionId?: string
    documentId?: string
  } = {},
): Promise<SessionListResponse> {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  })
  if (opts.mode) params.set("mode", opts.mode)
  if (opts.status) params.set("status", opts.status)
  if (opts.collectionId) params.set("collection_id", opts.collectionId)
  if (opts.documentId) params.set("document_id", opts.documentId)
  const res = await fetch(`${API_BASE}/study/sessions?${params.toString()}`)
  if (!res.ok) throw new Error("Failed to load sessions")
  return res.json() as Promise<SessionListResponse>
}

// ---------------------------------------------------------------------------
// Flashcard generation
// ---------------------------------------------------------------------------

export type Difficulty = "easy" | "medium" | "hard"

export async function generateDocumentFlashcards(
  documentId: string,
  count: number = 10,
  difficulty: Difficulty = "medium",
): Promise<number> {
  const res = await fetch(`${API_BASE}/flashcards/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      document_id: documentId,
      scope: "full",
      count,
      difficulty,
    }),
  })
  if (!res.ok) {
    const msg = res.status === 503
      ? "Ollama is not running. Start it with: ollama serve"
      : "Failed to generate flashcards"
    throw new Error(msg)
  }
  const cards = (await res.json()) as unknown[]
  return cards.length
}

export interface CollectionGenerationResult {
  totalCreated: number
  noteCreated: number
  noteSkipped: number
  documentsProcessed: number
  errors: string[]
}

export async function generateCollectionFlashcards(
  collectionId: string,
  sources: { id: string; type: "document" | "note" }[],
  count: number = 10,
  difficulty: Difficulty = "medium",
): Promise<CollectionGenerationResult> {
  const result: CollectionGenerationResult = {
    totalCreated: 0,
    noteCreated: 0,
    noteSkipped: 0,
    documentsProcessed: 0,
    errors: [],
  }

  const hasNotes = sources.some((s) => s.type === "note")
  if (hasNotes) {
    try {
      const res = await fetch(`${API_BASE}/notes/flashcards/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          collection_id: collectionId,
          count,
          difficulty,
        }),
      })
      if (res.ok) {
        const data = (await res.json()) as {
          created?: number
          skipped?: number
        }
        result.noteCreated = data.created ?? 0
        result.noteSkipped = data.skipped ?? 0
        result.totalCreated += result.noteCreated
      } else {
        result.errors.push(`Notes generation failed (HTTP ${res.status})`)
      }
    } catch (e) {
      result.errors.push(`Notes: ${e instanceof Error ? e.message : String(e)}`)
    }
  }

  const docIds = sources.filter((s) => s.type === "document").map((s) => s.id)
  for (const docId of docIds) {
    try {
      const created = await generateDocumentFlashcards(docId, count, difficulty)
      result.totalCreated += created
      result.documentsProcessed += 1
    } catch (e) {
      result.errors.push(
        `Document ${docId}: ${e instanceof Error ? e.message : String(e)}`,
      )
    }
  }

  return result
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function scoreBadgeClass(score: number): string {
  if (score >= 80) return "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
  if (score >= 60) return "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400"
  return "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
}
