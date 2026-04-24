/**
 * useStudySession -- in-session state holder and lifecycle actions.
 *
 * This hook does NOT create sessions. Session creation happens in
 * `prepareStudySession` (studySessionService.ts), which is called by event
 * handlers BEFORE this component mounts. The hook receives a prepared session
 * and manages the user's interaction with it (queue position, reviewed count,
 * completion, exit, start-new).
 *
 * Why: prior versions created sessions inside `useEffect([])`. Any mount
 * (StrictMode, parent key change, HMR, fast navigation) would spawn a new
 * backend session. Moving creation out of the mount effect makes session
 * creation strictly tied to user intent: one click, one call, one session.
 */

import { useCallback, useEffect, useRef, useState } from "react"
import {
  type Flashcard,
  type TeachbackResultItem,
  endSession,
} from "@/lib/studyApi"
import {
  type PreparedStudySession,
  type PrepareStudySessionOptions,
  prepareStudySession,
} from "@/lib/studySessionService"
import { useAppStore } from "@/store"

export type SessionState = "loading" | "studying" | "complete" | "empty"

export interface UseStudySessionInput {
  /** Session prepared by prepareStudySession. */
  initial:
    | { kind: "studying"; session: PreparedStudySession }
    | { kind: "complete"; session: PreparedStudySession }
    | { kind: "empty" }
  /** Options used for beginNew (Start New Session after completion). */
  scopeForBeginNew: PrepareStudySessionOptions
  /** Invoked once after a resume so the caller can seed pending-teach-back UI. */
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
  setQueue: React.Dispatch<React.SetStateAction<Flashcard[]>>
  setCurrentIndex: React.Dispatch<React.SetStateAction<number>>
  setReviewed: React.Dispatch<React.SetStateAction<number>>
  setSessionState: React.Dispatch<React.SetStateAction<SessionState>>
  completeSession: () => Promise<void>
  exit: (onExit: () => void) => Promise<void>
  beginNew: () => Promise<void>
}

export function useStudySession(
  input: UseStudySessionInput,
): UseStudySessionResult {
  const { setStudySessionId } = useAppStore()

  // Seed state once from the prepared session. React's lazy-init form runs
  // the factory exactly once; subsequent renders do not re-derive. This is
  // the critical invariant that replaces the broken mount-side-effect.
  const [sessionState, setSessionState] = useState<SessionState>(() =>
    input.initial.kind === "empty" ? "empty" : input.initial.kind,
  )
  const [sessionId, setSessionId] = useState<string | null>(() =>
    input.initial.kind === "empty" ? null : input.initial.session.id,
  )
  const [queue, setQueue] = useState<Flashcard[]>(() =>
    input.initial.kind === "empty" ? [] : input.initial.session.queue,
  )
  const [currentIndex, setCurrentIndex] = useState<number>(0)
  const [reviewed, setReviewed] = useState<number>(() =>
    input.initial.kind === "empty" ? 0 : input.initial.session.answeredCount,
  )
  const [total, setTotal] = useState<number>(() =>
    input.initial.kind === "empty" ? 0 : input.initial.session.plannedTotal,
  )

  // Fire the resume-loaded callback exactly once per component instance and
  // sync the Zustand session id so other UI knows a session is active. The
  // ref guard makes this StrictMode-safe: the second effect run skips the
  // callback because the ref has already flipped.
  const resumeDeliveredRef = useRef(false)
  const initialRef = useRef(input.initial)
  const onResumeLoadedRef = useRef(input.onResumeLoaded)
  onResumeLoadedRef.current = input.onResumeLoaded
  useEffect(() => {
    if (resumeDeliveredRef.current) return
    resumeDeliveredRef.current = true
    const snap = initialRef.current
    if (snap.kind === "empty") return
    setStudySessionId(snap.session.id)
    if (snap.session.prevResults.length > 0) {
      onResumeLoadedRef.current?.(snap.session.prevResults)
    }
  }, [setStudySessionId])

  const completeSession = useCallback(async () => {
    if (sessionId) {
      await endSession(sessionId).catch(() => {})
    }
    setSessionState("complete")
  }, [sessionId])

  const exit = useCallback(
    async (onExit: () => void) => {
      if (sessionId && sessionState !== "complete") {
        const remaining = Math.max(queue.length - currentIndex, 0)
        // Only finalise if the queue was exhausted without hitting complete.
        // reviewed=0 and partial-progress both stay open so a later Start
        // auto-resumes the same session instead of creating a duplicate.
        if (reviewed > 0 && remaining === 0) {
          await endSession(sessionId).catch(() => {})
        }
      }
      setStudySessionId(null)
      onExit()
    },
    [
      sessionId,
      sessionState,
      queue.length,
      currentIndex,
      reviewed,
      setStudySessionId,
    ],
  )

  const beginNewInFlightRef = useRef(false)
  const beginNew = useCallback(async () => {
    // Begin New -> explicitly asks for a fresh session for the same scope.
    // We still go through prepareStudySession so that auto-resume and
    // empty-case handling are identical to the first-start path. The ref
    // guard drops a double-click before state updates can hide the button.
    if (beginNewInFlightRef.current) return
    beginNewInFlightRef.current = true
    try {
      setSessionState("loading")
      const outcome = await prepareStudySession(input.scopeForBeginNew)
      if (outcome.kind === "empty") {
        setSessionId(null)
        setQueue([])
        setCurrentIndex(0)
        setReviewed(0)
        setTotal(0)
        setStudySessionId(null)
        setSessionState("empty")
        return
      }
      const s = outcome.session
      setSessionId(s.id)
      setStudySessionId(s.id)
      setQueue(s.queue)
      setCurrentIndex(0)
      setReviewed(s.answeredCount)
      setTotal(s.plannedTotal)
      setSessionState(outcome.kind)
    } finally {
      beginNewInFlightRef.current = false
    }
  }, [input.scopeForBeginNew, setStudySessionId])

  return {
    sessionState,
    sessionId,
    queue,
    currentIndex,
    reviewed,
    total,
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
