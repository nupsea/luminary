/**
 * Shared types and API functions for study sessions (Flashcard + Teach-back).
 *
 * Both FlashcardSession and TeachbackSession import from here to avoid duplication.
 * Uses the shared apiClient (#12 standardisation).
 */

import {
  ApiError,
  apiDelete,
  apiGet,
  apiPost,
  type QueryParams,
} from "@/lib/apiClient"

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
// Helpers
// ---------------------------------------------------------------------------

/** Resolves a fetch that should silently fall back on any error. */
async function tryOr<T>(fn: () => Promise<T>, fallback: T): Promise<T> {
  try {
    return await fn()
  } catch {
    return fallback
  }
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
  try {
    const data = await apiPost<{ id: string }>("/study/sessions/start", {
      document_id: documentId,
      collection_id: collectionId,
      mode,
      planned_card_ids: plannedCardIds,
    })
    return data.id
  } catch {
    throw new Error("Failed to start session")
  }
}

export interface SessionRemainingState {
  answered_count: number
  planned_count: number
  cards: Flashcard[]
}

export const fetchSessionRemainingCards = (
  sessionId: string,
): Promise<SessionRemainingState> =>
  tryOr(
    () =>
      apiGet<SessionRemainingState>(
        `/study/sessions/${encodeURIComponent(sessionId)}/remaining-cards`,
      ),
    { answered_count: 0, planned_count: 0, cards: [] },
  )

/** Most recent open session for this scope, or null if none. */
export async function fetchOpenSession(params: {
  mode: string
  documentId: string | null
  collectionId: string | null
}): Promise<{ id: string } | null> {
  try {
    const data = await apiGet<{ id: string }>("/study/sessions/open", {
      mode: params.mode,
      document_id: params.documentId,
      collection_id: params.collectionId,
    })
    return { id: data.id }
  } catch {
    return null
  }
}

export const fetchDueCards = (
  documentId: string | null,
  collectionId: string | null = null,
  filters: {
    tag?: string
    document_ids?: string[]
    note_ids?: string[]
    limit?: number
  } = {},
): Promise<Flashcard[]> => {
  const params: QueryParams = {
    limit: filters.limit ?? 50,
    document_id: documentId,
    collection_id: collectionId,
    tag: filters.tag,
  }
  // Repeated-key params (document_ids, note_ids) aren't expressible through
  // QueryParams; build the URL manually for those.
  const url = new URL("https://placeholder")
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined) url.searchParams.set(k, String(v))
  }
  filters.document_ids?.forEach((id) => url.searchParams.append("document_ids", id))
  filters.note_ids?.forEach((id) => url.searchParams.append("note_ids", id))
  const path = `/study/due?${url.searchParams.toString()}`
  return tryOr(() => apiGet<Flashcard[]>(path), [])
}

export async function submitReview(
  cardId: string,
  rating: Rating,
  sessionId: string,
): Promise<void> {
  try {
    await apiPost(`/flashcards/${cardId}/review`, {
      rating,
      session_id: sessionId,
    })
  } catch {
    // Original implementation also swallowed errors here.
  }
}

export async function endSession(sessionId: string): Promise<void> {
  try {
    await apiPost(`/study/sessions/${sessionId}/end`)
  } catch {
    // Original implementation swallowed errors here.
  }
}

export async function reopenSession(sessionId: string): Promise<void> {
  try {
    await apiPost(`/study/sessions/${encodeURIComponent(sessionId)}/reopen`)
  } catch {
    // Original implementation swallowed errors here.
  }
}

export async function deleteStudySession(sessionId: string): Promise<void> {
  try {
    await apiDelete(`/study/sessions/${encodeURIComponent(sessionId)}`)
  } catch {
    throw new Error("Failed to delete session")
  }
}

export const fetchSourceContext = (
  cardId: string,
): Promise<SourceContext | null> =>
  tryOr(
    () =>
      apiGet<SourceContext>(
        `/flashcards/${encodeURIComponent(cardId)}/source-context`,
      ),
    null,
  )

// ---------------------------------------------------------------------------
// Teach-back API
// ---------------------------------------------------------------------------

export async function submitTeachbackAsync(
  flashcardId: string,
  userExplanation: string,
  sessionId: string | null = null,
): Promise<{ id: string }> {
  try {
    return await apiPost<{ id: string }>("/study/teachback/async", {
      flashcard_id: flashcardId,
      user_explanation: userExplanation,
      session_id: sessionId,
    })
  } catch {
    throw new Error("Teachback submit failed")
  }
}

export async function fetchTeachbackResults(
  ids: string[],
): Promise<TeachbackResultItem[]> {
  if (ids.length === 0) return []
  try {
    const data = await apiGet<{ results: TeachbackResultItem[] }>(
      `/study/teachback/results?ids=${ids.join(",")}`,
    )
    return data.results
  } catch {
    throw new Error("Failed to fetch teachback results")
  }
}

export const fetchSessionTeachbackResults = (
  sessionId: string,
): Promise<TeachbackResultItem[]> =>
  tryOr(
    async () => {
      const data = await apiGet<{ results: TeachbackResultItem[] }>(
        `/study/sessions/${encodeURIComponent(sessionId)}/teachback-results`,
      )
      return data.results
    },
    [],
  )

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
  try {
    return await apiGet<SessionListResponse>("/study/sessions", {
      page,
      page_size: pageSize,
      mode: opts.mode,
      status: opts.status,
      collection_id: opts.collectionId,
      document_id: opts.documentId,
    })
  } catch {
    throw new Error("Failed to load sessions")
  }
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
  try {
    const cards = await apiPost<unknown[]>("/flashcards/generate", {
      document_id: documentId,
      scope: "full",
      count,
      difficulty,
    })
    return cards.length
  } catch (err) {
    if (err instanceof ApiError && err.status === 503) {
      throw new Error("Ollama is not running. Start it with: ollama serve")
    }
    throw new Error("Failed to generate flashcards")
  }
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
      const data = await apiPost<{ created?: number; skipped?: number }>(
        "/notes/flashcards/generate",
        { collection_id: collectionId, count, difficulty },
      )
      result.noteCreated = data.created ?? 0
      result.noteSkipped = data.skipped ?? 0
      result.totalCreated += result.noteCreated
    } catch (e) {
      if (e instanceof ApiError) {
        result.errors.push(`Notes generation failed (HTTP ${e.status})`)
      } else {
        result.errors.push(`Notes: ${e instanceof Error ? e.message : String(e)}`)
      }
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
