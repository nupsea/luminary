/**
 * studySessionService -- the single async entry point for preparing a study
 * session. ALL backend calls to start/resume/reopen sessions funnel through
 * here and are triggered by explicit user events (button handlers), never by
 * component mount effects. This is what keeps "one user action = one session"
 * true regardless of React remount/StrictMode/HMR behavior.
 */

import {
  type Flashcard,
  type TeachbackResultItem,
  endSession,
  fetchDueCards,
  fetchOpenSession,
  fetchSessionRemainingCards,
  fetchSessionTeachbackResults,
  reopenSession,
  startSession,
} from "@/lib/studyApi"

export type StudyMode = "flashcard" | "teachback"

export interface StudyFilters {
  tag?: string
  document_ids?: string[]
  note_ids?: string[]
  section_id?: string
}

export interface PrepareStudySessionOptions {
  mode: StudyMode
  documentId?: string | null
  collectionId?: string | null
  filters?: StudyFilters
  cardLimit: number
  /** If set, resume this specific session (used by Continue/Resume buttons). */
  resumeSessionId?: string | null
}

export type PreparedStudySessionOutcome =
  | { kind: "studying"; session: PreparedStudySession }
  | { kind: "complete"; session: PreparedStudySession }
  | { kind: "empty" }

export interface PreparedStudySession {
  id: string
  mode: StudyMode
  queue: Flashcard[]
  prevResults: TeachbackResultItem[]
  answeredCount: number
  plannedTotal: number
  documentId: string | null
  collectionId: string | null
}

/**
 * Resolve the session the user wants and return its runtime state.
 *
 * Precedence (the FIRST match wins, no fallthrough between branches unless
 * explicitly noted):
 *   1. resumeSessionId set: reattach to that specific session, even if it has
 *      no remaining work (caller shows complete screen).
 *   2. An open session already exists for this exact scope (mode + documentId
 *      + collectionId) and it has real content: adopt it.
 *   3. Open session exists but is empty (no planned queue and no prior work,
 *      e.g. legacy pre-migration row): end it silently, then create fresh.
 *   4. No open session: create fresh -- fetching due cards and persisting them
 *      as the planned queue so future resumes reconstruct the exact same set.
 */
export async function prepareStudySession(
  opts: PrepareStudySessionOptions,
): Promise<PreparedStudySessionOutcome> {
  const {
    mode,
    documentId = null,
    collectionId = null,
    filters,
    cardLimit,
    resumeSessionId = null,
  } = opts

  // 1. Explicit resume
  if (resumeSessionId) {
    const outcome = await reattach(resumeSessionId, {
      mode,
      documentId,
      collectionId,
      allowEmpty: true,
    })
    if (outcome) return outcome
    // Requested session vanished; fall through to a fresh start.
  }

  // 2/3. Auto-resume the scope's open session if any
  const existing = await fetchOpenSession({
    mode,
    documentId,
    collectionId,
  })
  if (existing) {
    const outcome = await reattach(existing.id, {
      mode,
      documentId,
      collectionId,
      allowEmpty: false,
    })
    if (outcome) return outcome
    // Stale/empty: close it so it stops matching /sessions/open.
    await endSession(existing.id).catch(() => {})
  }

  // 4. Create fresh
  const rawCards = await fetchDueCards(documentId, collectionId, {
    ...(filters || {}),
    limit: cardLimit,
  })
  if (rawCards.length === 0) {
    return { kind: "empty" }
  }

  // Shape the queue: warm-up first (high stability + multiple reps), engage last.
  const cards = shapeQueue(rawCards)

  const id = await startSession(
    documentId,
    mode,
    collectionId,
    cards.map((c) => c.id),
  )
  return {
    kind: "studying",
    session: {
      id,
      mode,
      queue: cards,
      prevResults: [],
      answeredCount: 0,
      plannedTotal: cards.length,
      documentId,
      collectionId,
    },
  }
}

/**
 * Study one coherent SECTION (a chapter or sub-section) from an EXPLICIT set of cards (its existing
 * cards, or ones just generated for it) -- not a due round-trip, so freshly generated cards always
 * appear and a not-yet-due section can still be studied. Always fresh: it does not adopt the
 * document's open session (scoped by doc, not section), so two sections never cross-contaminate.
 */
export async function prepareSectionStudyFromCards(
  documentId: string,
  cards: Flashcard[],
  mode: StudyMode = "flashcard",
): Promise<PreparedStudySessionOutcome> {
  if (cards.length === 0) return { kind: "empty" }
  const shaped = shapeQueue(cards)
  const id = await startSession(
    documentId,
    mode,
    null,
    shaped.map((c) => c.id),
  )
  return {
    kind: "studying",
    session: {
      id,
      mode,
      queue: shaped,
      prevResults: [],
      answeredCount: 0,
      plannedTotal: shaped.length,
      documentId,
      collectionId: null,
    },
  }
}

async function reattach(
  sid: string,
  ctx: {
    mode: StudyMode
    documentId: string | null
    collectionId: string | null
    allowEmpty: boolean
  },
): Promise<PreparedStudySessionOutcome | null> {
  const [prevResults, remaining] = await Promise.all([
    fetchSessionTeachbackResults(sid),
    fetchSessionRemainingCards(sid),
  ])

  const hasPrior = prevResults.length > 0 || remaining.answered_count > 0
  const hasRemaining = remaining.cards.length > 0
  if (!hasPrior && !hasRemaining && !ctx.allowEmpty) {
    return null
  }

  const plannedTotal =
    remaining.planned_count > 0
      ? remaining.planned_count
      : prevResults.length + remaining.cards.length
  const answeredCount = Math.max(prevResults.length, remaining.answered_count)

  if (hasRemaining) {
    await reopenSession(sid).catch(() => {})
    return {
      kind: "studying",
      session: {
        id: sid,
        mode: ctx.mode,
        queue: remaining.cards,
        prevResults,
        answeredCount,
        plannedTotal,
        documentId: ctx.documentId,
        collectionId: ctx.collectionId,
      },
    }
  }

  return {
    kind: "complete",
    session: {
      id: sid,
      mode: ctx.mode,
      queue: [],
      prevResults,
      answeredCount,
      plannedTotal,
      documentId: ctx.documentId,
      collectionId: ctx.collectionId,
    },
  }
}

// Sort cards into warm-up → engage order.
// Warm-up: top 25% by stability (well-retained, comfortable to recall).
// Engage: remaining cards (lower stability, newer, harder).
function shapeQueue(cards: Flashcard[]): Flashcard[] {
  if (cards.length <= 3) return cards
  const sorted = [...cards].sort((a, b) => b.fsrs_stability - a.fsrs_stability)
  const warmUpCount = Math.max(1, Math.floor(cards.length * 0.25))
  const warmUp = sorted.slice(0, warmUpCount)
  const engage = sorted.slice(warmUpCount)
  // Shuffle engage bucket so high-stability cards don't cluster together there too.
  for (let i = engage.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[engage[i], engage[j]] = [engage[j], engage[i]]
  }
  return [...warmUp, ...engage]
}
