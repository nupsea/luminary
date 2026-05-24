/**
 * Unified ⌘K search adapter layer (2D.3).
 *
 * Each backend endpoint returns its own shape. This module normalizes
 * those shapes into a single discriminated union so SearchDialog never
 * has to know about per-endpoint fields. The parallel fetch is the
 * easy part -- this adapter layer is the decoupling work.
 */

import { apiGet } from "@/lib/apiClient"
import type { components } from "@/types/api"

type SearchResponse = components["schemas"]["SearchResponse"]
type NoteSearchResponse = components["schemas"]["NoteSearchResponse"]
type FlashcardSearchResponse = components["schemas"]["FlashcardSearchResponse"]

export type SearchKind = "document" | "note" | "flashcard"

export interface UnifiedSearchResult {
  kind: SearchKind
  /** Stable per-result key for React lists. Composed of `${kind}:${innerId}[:suffix]`. */
  key: string
  /** Primary identifier (chunk_id, note_id, or flashcard_id depending on kind). */
  id: string
  /** Title to display in the result row. */
  title: string
  /** Snippet line under the title. May be empty. */
  snippet: string
  /** Best-effort relevance score (higher = better). */
  score: number
  /** Owning document id when the result hangs off one (notes, flashcards, doc chunks). */
  documentId: string | null
  /** Free-form sub-line (section heading, page, deck source, etc.). */
  context: string
  /** Original content_type for the doc kind, or 'note' / 'flashcard' for the others. */
  contentType: string
}

// Adapters ---------------------------------------------------------------

export function adaptDocumentResults(resp: SearchResponse): UnifiedSearchResult[] {
  const out: UnifiedSearchResult[] = []
  for (const group of resp.results) {
    for (const m of group.matches) {
      const ctxParts = [m.section_heading || "", m.page > 0 ? `p.${m.page}` : ""].filter(Boolean)
      out.push({
        kind: "document",
        key: `document:${m.chunk_id}`,
        id: m.chunk_id,
        title: group.document_title,
        snippet: m.text_excerpt,
        score: m.relevance_score,
        documentId: m.document_id,
        context: ctxParts.join(" · "),
        contentType: group.content_type,
      })
    }
  }
  return out
}

export function adaptNoteResults(resp: NoteSearchResponse): UnifiedSearchResult[] {
  return resp.results.map((r) => ({
    kind: "note",
    key: `note:${r.note_id}`,
    id: r.note_id,
    title: deriveNoteTitle(r.content),
    snippet: r.content.slice(0, 240),
    score: r.score,
    documentId: r.document_id,
    context: r.group_name ?? r.tags.slice(0, 3).join(", "),
    contentType: "note",
  }))
}

export function adaptFlashcardResults(
  resp: FlashcardSearchResponse,
): UnifiedSearchResult[] {
  return resp.items.map((c) => ({
    kind: "flashcard",
    key: `flashcard:${c.id}`,
    id: c.id,
    title: c.question,
    snippet: c.answer,
    // /flashcards/search doesn't return a score per card. Use a small constant
    // so they sort below scored doc/note hits but above zero-relevance noise.
    score: 0.5,
    documentId: c.document_id,
    context: c.flashcard_type ?? c.source ?? "",
    contentType: "flashcard",
  }))
}

function deriveNoteTitle(content: string): string {
  const firstLine = content.split("\n", 1)[0] ?? ""
  const stripped = firstLine.replace(/^#+\s*/, "").trim()
  return (stripped || content.trim() || "Untitled note").slice(0, 120)
}

// Aggregator -------------------------------------------------------------

export interface UnifiedSearchOptions {
  q: string
  kinds?: SearchKind[]
  limit?: number
}

const KIND_PRIORITY: Record<SearchKind, number> = {
  document: 3,
  note: 2,
  flashcard: 1,
}

export async function fetchUnifiedSearch({
  q,
  kinds,
  limit = 20,
}: UnifiedSearchOptions): Promise<UnifiedSearchResult[]> {
  const trimmed = q.trim()
  if (!trimmed) return []
  const enabled = new Set<SearchKind>(kinds && kinds.length > 0 ? kinds : ["document", "note", "flashcard"])

  const docs = enabled.has("document")
    ? apiGet<SearchResponse>("/search", { q: trimmed, limit }).then(adaptDocumentResults).catch(() => [])
    : Promise.resolve<UnifiedSearchResult[]>([])
  const notes = enabled.has("note")
    ? apiGet<NoteSearchResponse>("/notes/search", { q: trimmed, k: limit })
        .then(adaptNoteResults)
        .catch(() => [])
    : Promise.resolve<UnifiedSearchResult[]>([])
  const cards = enabled.has("flashcard")
    ? apiGet<FlashcardSearchResponse>("/flashcards/search", {
        query: trimmed,
        page_size: limit,
      })
        .then(adaptFlashcardResults)
        .catch(() => [])
    : Promise.resolve<UnifiedSearchResult[]>([])

  const [d, n, c] = await Promise.all([docs, notes, cards])
  const merged = [...d, ...n, ...c]
  merged.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score
    return KIND_PRIORITY[b.kind] - KIND_PRIORITY[a.kind]
  })
  return merged
}

// Recent seeks (2D.4) ----------------------------------------------------

const RECENT_KEY = "luminary:recentSeeks"
const RECENT_MAX = 5

export function loadRecentSeeks(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((s): s is string => typeof s === "string").slice(0, RECENT_MAX)
  } catch {
    return []
  }
}

export function pushRecentSeek(q: string): void {
  const trimmed = q.trim()
  if (!trimmed) return
  try {
    const current = loadRecentSeeks().filter((s) => s !== trimmed)
    current.unshift(trimmed)
    localStorage.setItem(RECENT_KEY, JSON.stringify(current.slice(0, RECENT_MAX)))
  } catch {
    // Quota / privacy mode: drop silently.
  }
}
