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
  appendSessionCards,
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
 * The reader's Practice run: ONE session per document per mode, kept open.
 *
 * The panel used to start a fresh session on every click, so a document
 * accumulated a run per visit and nothing carried forward. A learner does not
 * think of themselves as starting a new relationship with a chapter each time
 * they open it -- they think of one practice on this document, that they add to.
 * So: adopt the open session for this scope when there is one, and create one
 * from the cards in front of the learner otherwise.
 *
 * Not `prepareStudySession`, which creates from a due-cards round trip: the
 * panel offers a run over the deck it is showing, including cards that are not
 * due yet, and a freshly generated card must appear in the run that generated it.
 *
 * Section scope narrows what the panel shows and what the generator writes from,
 * never which session is running. The session's scope is the document, so a
 * chapter's cards join the document's run rather than forking a parallel one
 * that the deck screen could never find again.
 */
export async function prepareContinuousStudySession(opts: {
  documentId: string
  mode: StudyMode
  cards: Flashcard[]
}): Promise<PreparedStudySessionOutcome> {
  const { documentId, mode, cards } = opts
  const ctx = { mode, documentId, collectionId: null, allowEmpty: false }
  const existing = await fetchOpenSession({ mode, documentId, collectionId: null })
  if (existing) {
    const outcome = await reattach(existing.id, ctx)
    if (outcome?.kind === "studying") return outcome
    if (outcome?.kind === "complete") {
      // The run is caught up, not over. Showing its summary here is what
      // pressing "Explain it" on a deck full of cards used to do -- it landed
      // the learner in the readout of a run they finished days ago. A run that
      // continues is the point of this function, so extend it with what the
      // panel is showing and carry on in the same session.
      const appended = await appendSessionCards(
        existing.id,
        cards.map((c) => c.id),
      ).catch(() => null)
      if (appended && appended.added > 0) {
        await reopenSession(existing.id).catch(() => {})
        const resumed = await reattach(existing.id, ctx)
        if (resumed?.kind === "studying") return resumed
      }
      // Nothing new to add: the summary IS the honest answer here.
      return outcome
    }
    // Stale or empty: close it so it stops matching /sessions/open.
    await endSession(existing.id).catch(() => {})
  }
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

// One scope should hold one open run per mode, but a second window, a crashed
// tab or a script can leave more. This is the ceiling on how many are closed in
// one pass, not a claim that a scope may have that many.
const MAX_OPEN_SESSIONS_PER_SCOPE = 10

// Close any open flashcard/teach-back session for a scope. Call after deleting
// or regenerating a scope's cards so the next study run starts fresh instead of
// resuming a session whose planned cards no longer exist.
export async function endOpenSessionsForScope(
  documentId: string | null,
  collectionId: string | null,
): Promise<void> {
  const modes: StudyMode[] = ["flashcard", "teachback"]
  await Promise.all(
    modes.map(async (mode) => {
      // EVERY open session for the mode, not the newest one. /sessions/open
      // returns one row, and closing only that left a second run open on the
      // same document -- the panel then adopted it, inherited a plan of cards
      // the replacement had just deleted, and appended the fresh ones to it.
      // Bounded rather than while(true): endSession swallows its errors, so an
      // unclosable session must not spin here.
      for (let i = 0; i < MAX_OPEN_SESSIONS_PER_SCOPE; i++) {
        const open = await fetchOpenSession({ mode, documentId, collectionId }).catch(() => null)
        if (!open) return
        await endSession(open.id).catch(() => {})
      }
    }),
  )
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
  // Distinct cards, never rows. `prevResults` is one row per ATTEMPT and a card
  // can be answered many times in a continuous run, while the backend's
  // `answered_count` is already a set of ids -- so a Math.max across the two
  // units picks the attempt count. The header read "30 of 15 reviewed" on a
  // session holding 30 attempts across 5 cards. The max itself is still needed:
  // `answered_count` is restricted to the planned set, and a result for a card
  // that has since left the plan still happened.
  const answeredCount = Math.max(
    new Set(prevResults.map((r) => r.flashcard_id)).size,
    remaining.answered_count,
  )
  // A session is STALE when its planned cards were deleted/regenerated: there's
  // no live remaining work, yet it never reviewed its whole plan. Such a session
  // must NOT resurface as a stuck "complete" screen whose "Start Next Set" just
  // re-resumes the same dead session -- return null so the caller closes it and
  // starts fresh. A genuinely finished session (everything reviewed) is still
  // adopted so re-entry shows its results, and the explicit-resume path
  // (allowEmpty) always reattaches.
  //
  // A plan of ZERO is the same thing at its limit: since planned_count counts
  // only cards that still exist (I-47), a run whose whole deck was replaced now
  // reports nothing planned rather than a count that outruns what was answered,
  // and the old `planned_count > answeredCount` test alone stopped seeing it.
  const isStale =
    !hasRemaining && (remaining.planned_count === 0 || remaining.planned_count > answeredCount)
  if (!ctx.allowEmpty && ((!hasPrior && !hasRemaining) || isStale)) {
    return null
  }

  // Reconcile the planned total against what's actually live. The server now
  // counts only planned cards that still exist (I-47), so this is the narrower
  // guard it was always meant to be: a card deleted between those two calls, or
  // an answered card that has since left the plan. It cannot see the case it
  // used to be relied on for -- when the plan holds deleted cards, planned_count
  // and answered inflate together and the min agrees with both.
  const liveTotal = answeredCount + remaining.cards.length
  const plannedTotal =
    remaining.planned_count > 0
      ? Math.min(remaining.planned_count, liveTotal)
      : liveTotal

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
