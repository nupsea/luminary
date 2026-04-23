/**
 * useStudySession -- consolidated lifecycle for a study session.
 *
 * Owns: start-session, StrictMode-safe single init, fetchDueCards with mode
 * limit, empty→auto-end, resume flow, unmount→auto-end-if-incomplete, and the
 * "begin next" reset used by the SessionComplete screen.
 *
 * Does NOT own per-card rating/teachback state; those stay with the caller.
 *
 * This exists because StudySession and TeachbackSession previously had two
 * parallel copies of this logic, and every lifecycle bug (double session,
 * lingering IN PROGRESS, resume races, card-limit drift) had to be fixed in
 * two places. See also: I-style patterns in architecture.md.
 */

import { useCallback, useEffect, useRef, useState } from "react"
import {
  type Flashcard,
  type TeachbackResultItem,
  endSession,
  deleteStudySession,
  fetchDueCards,
  fetchSessionTeachbackResults,
  startSession,
} from "@/lib/studyApi"
import { useAppStore } from "@/store"

export type SessionState = "loading" | "studying" | "complete" | "empty"

export type StudyMode = "flashcard" | "teachback"

export interface StudyFilters {
  tag?: string
  document_ids?: string[]
  note_ids?: string[]
}

export interface UseStudySessionOptions {
  mode: StudyMode
  documentId?: string | null
  collectionId?: string | null
  filters?: StudyFilters
  cardLimit: number
  /** If set, the hook loads prior teach-back results and surfaces them via onResumeLoaded. */
  resumeSessionId?: string | null
  /** Invoked once with the prior teach-back results when resuming a session. */
  onResumeLoaded?: (prev: TeachbackResultItem[]) => void
}

export interface UseStudySessionResult {
  sessionState: SessionState
  sessionId: string | null
  queue: Flashcard[]
  currentIndex: number
  reviewed: number
  total: number
  currentCard: Flashcard | null
  /** Mutators the caller uses to drive card-level advancement / requeue. */
  setQueue: React.Dispatch<React.SetStateAction<Flashcard[]>>
  setCurrentIndex: React.Dispatch<React.SetStateAction<number>>
  setReviewed: React.Dispatch<React.SetStateAction<number>>
  setSessionState: React.Dispatch<React.SetStateAction<SessionState>>
  /** End the session on the backend and move to "complete". */
  completeSession: () => Promise<void>
  /** End the session (if still open) and invoke onExit. Use from a Back button. */
  exit: (onExit: () => void) => Promise<void>
  /** Reset all state and start a fresh session in-place (Start New Session). */
  beginNew: () => void
}

export function useStudySession(
  options: UseStudySessionOptions,
): UseStudySessionResult {
  const {
    mode,
    documentId,
    collectionId,
    filters,
    cardLimit,
    resumeSessionId,
    onResumeLoaded,
  } = options

  const [sessionState, setSessionState] = useState<SessionState>("loading")
  const [sessionId, setSessionId] = useState<string | null>(
    resumeSessionId ?? null,
  )
  const [queue, setQueue] = useState<Flashcard[]>([])
  const [currentIndex, setCurrentIndex] = useState(0)
  const [reviewed, setReviewed] = useState(0)

  const { setStudySessionId } = useAppStore()

  const initialTotalRef = useRef<number>(0)
  // StrictMode double-mount guard -- without this, two backend sessions are
  // created on the first mount and the first stays "IN PROGRESS" forever.
  const didStartRef = useRef(false)
  // Track the last-known sessionState without triggering the unmount effect
  // to rerun when it changes.
  const sessionStateRef = useRef<SessionState>("loading")
  useEffect(() => {
    sessionStateRef.current = sessionState
  }, [sessionState])
  const sessionIdRef = useRef<string | null>(sessionId)
  useEffect(() => {
    sessionIdRef.current = sessionId
  }, [sessionId])

  // One-time init (handles both resume and fresh start). The didStartRef guard
  // keeps us StrictMode-safe; the `cancelled` flag suppresses state writes if
  // React tears down before the async work settles.
  useEffect(() => {
    if (didStartRef.current) return
    didStartRef.current = true
    let cancelled = false

    async function init() {
      try {
        if (resumeSessionId) {
          // Resume: no new session, load prior results + remaining cards.
          const [prevResults, cards] = await Promise.all([
            fetchSessionTeachbackResults(resumeSessionId),
            fetchDueCards(documentId || null, collectionId || null, {
              ...(filters || {}),
              limit: cardLimit,
            }),
          ])
          if (cancelled) return

          onResumeLoaded?.(prevResults)
          setReviewed(prevResults.length)

          const answeredCardIds = new Set(
            prevResults.map((r) => r.flashcard_id),
          )
          const remainingCards = cards.filter(
            (c) => !answeredCardIds.has(c.id),
          )
          initialTotalRef.current =
            prevResults.length + remainingCards.length

          if (remainingCards.length > 0) {
            setQueue(remainingCards)
            setSessionState("studying")
          } else {
            setSessionState("complete")
          }
          return
        }

        const [sid, cards] = await Promise.all([
          startSession(documentId ?? null, mode, collectionId ?? null),
          fetchDueCards(documentId || null, collectionId || null, {
            ...(filters || {}),
            limit: cardLimit,
          }),
        ])
        if (cancelled) {
          void deleteStudySession(sid).catch(() => {})
          return
        }

        setSessionId(sid)
        setStudySessionId(sid)
        setQueue(cards)
        initialTotalRef.current = cards.length

        if (cards.length === 0) {
          // End immediately so no blank IN PROGRESS row lingers in history.
          void endSession(sid).catch(() => {})
          setSessionState("empty")
        } else {
          setSessionState("studying")
        }
      } catch {
        if (!cancelled) setSessionState("empty")
      }
    }

    void init()
    return () => {
      cancelled = true
      didStartRef.current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Unmount safety net: if the component is destroyed mid-session (e.g. user
  // navigates away), close the session on the backend so it doesn't linger.
  useEffect(() => {
    return () => {
      const sid = sessionIdRef.current
      const state = sessionStateRef.current
      if (sid && state !== "complete" && state !== "empty") {
        void endSession(sid).catch(() => {})
      }
    }
  }, [])

  const completeSession = useCallback(async () => {
    if (sessionId) {
      await endSession(sessionId).catch(() => {})
    }
    setSessionState("complete")
  }, [sessionId])

  const exit = useCallback(
    async (onExit: () => void) => {
      if (sessionId && sessionStateRef.current !== "complete") {
        await endSession(sessionId).catch(() => {})
      }
      setStudySessionId(null)
      onExit()
    },
    [sessionId, setStudySessionId],
  )

  const beginNew = useCallback(() => {
    setQueue([])
    setCurrentIndex(0)
    setReviewed(0)
    initialTotalRef.current = 0
    setSessionId(null)
    setSessionState("loading")
    void (async () => {
      try {
        const [sid, cards] = await Promise.all([
          startSession(documentId ?? null, mode, collectionId ?? null),
          fetchDueCards(documentId || null, collectionId || null, {
            ...(filters || {}),
            limit: cardLimit,
          }),
        ])
        setSessionId(sid)
        setStudySessionId(sid)
        setQueue(cards)
        initialTotalRef.current = cards.length
        if (cards.length === 0) {
          void endSession(sid).catch(() => {})
          setSessionState("empty")
        } else {
          setSessionState("studying")
        }
      } catch {
        setSessionState("empty")
      }
    })()
  }, [
    mode,
    documentId,
    collectionId,
    filters,
    cardLimit,
    setStudySessionId,
  ])

  return {
    sessionState,
    sessionId,
    queue,
    currentIndex,
    reviewed,
    total: initialTotalRef.current,
    currentCard: queue[currentIndex] ?? null,
    setQueue,
    setCurrentIndex,
    setReviewed,
    setSessionState,
    completeSession,
    exit,
    beginNew,
  }
}
