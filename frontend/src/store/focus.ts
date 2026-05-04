// ---------------------------------------------------------------------------
// focus store (S209) -- Zustand state machine for the global FocusTimerPill.
// Holds the current session id, phase, and remaining seconds. Persists a small
// snapshot to localStorage so a refresh inside an active session can rehydrate.
// ---------------------------------------------------------------------------

import { create } from "zustand"
import type { Surface } from "@/lib/focusUtils"

export type FocusPhase = "idle" | "focus" | "paused" | "break"

export interface FocusState {
  sessionId: string | null
  phase: FocusPhase
  secondsLeft: number
  focusMinutes: number
  breakMinutes: number
  surface: Surface
  goalId: string | null
  muted: boolean
  // Wall-clock timestamp of the last tick. Used to reconcile after a refresh.
  lastTickAt: number | null
  // Inline error surfaced under the pill.
  errorMessage: string | null

  // Setters / control actions. Async-ish bookkeeping (API calls) lives in the
  // component layer; the store stays a pure state machine.
  setSession: (sessionId: string, phase: FocusPhase, secondsLeft: number) => void
  enterFocus: (sessionId: string, secondsLeft: number) => void
  enterPaused: () => void
  enterBreak: (secondsLeft: number) => void
  enterIdle: () => void
  tick: () => void
  setFocusMinutes: (m: number) => void
  setBreakMinutes: (m: number) => void
  setSurface: (s: Surface) => void
  setGoalId: (id: string | null) => void
  setMuted: (m: boolean) => void
  setError: (e: string | null) => void
  // Hydrate state from a persisted snapshot. Pure -- no side effects.
  hydrate: (snapshot: Partial<FocusState>) => void
}

export const FOCUS_STORAGE_KEY = "luminary:focusTimer"

export const DEFAULT_FOCUS_MINUTES = 25
export const DEFAULT_BREAK_MINUTES = 5

export interface FocusSnapshot {
  sessionId: string | null
  phase: FocusPhase
  secondsLeft: number
  focusMinutes: number
  breakMinutes: number
  surface: Surface
  goalId: string | null
  muted: boolean
  lastTickAt: number | null
}

function readSnapshot(): Partial<FocusSnapshot> {
  if (typeof localStorage === "undefined") return {}
  try {
    const raw = localStorage.getItem(FOCUS_STORAGE_KEY)
    if (!raw) return {}
    return JSON.parse(raw) as Partial<FocusSnapshot>
  } catch {
    return {}
  }
}

export function writeSnapshot(s: FocusSnapshot): void {
  if (typeof localStorage === "undefined") return
  try {
    localStorage.setItem(FOCUS_STORAGE_KEY, JSON.stringify(s))
  } catch {
    // Quota or privacy mode -- ignore.
  }
}

export function clearSnapshot(): void {
  if (typeof localStorage === "undefined") return
  try {
    localStorage.removeItem(FOCUS_STORAGE_KEY)
  } catch {
    // Ignore.
  }
}

const initial = readSnapshot()

export const useFocusStore = create<FocusState>((set) => ({
  sessionId: initial.sessionId ?? null,
  phase: initial.phase ?? "idle",
  secondsLeft: initial.secondsLeft ?? (initial.focusMinutes ?? DEFAULT_FOCUS_MINUTES) * 60,
  focusMinutes: initial.focusMinutes ?? DEFAULT_FOCUS_MINUTES,
  breakMinutes: initial.breakMinutes ?? DEFAULT_BREAK_MINUTES,
  surface: initial.surface ?? "none",
  goalId: initial.goalId ?? null,
  muted: initial.muted ?? false,
  lastTickAt: initial.lastTickAt ?? null,
  errorMessage: null,

  setSession: (sessionId, phase, secondsLeft) =>
    set({ sessionId, phase, secondsLeft, lastTickAt: Date.now(), errorMessage: null }),

  enterFocus: (sessionId, secondsLeft) =>
    set({
      sessionId,
      phase: "focus",
      secondsLeft,
      lastTickAt: Date.now(),
      errorMessage: null,
    }),

  enterPaused: () => set({ phase: "paused", lastTickAt: Date.now() }),

  enterBreak: (secondsLeft) =>
    set({ phase: "break", secondsLeft, lastTickAt: Date.now() }),

  enterIdle: () =>
    set((state) => ({
      sessionId: null,
      phase: "idle",
      secondsLeft: state.focusMinutes * 60,
      lastTickAt: null,
      errorMessage: null,
    })),

  tick: () =>
    set((state) => {
      if (state.phase !== "focus" && state.phase !== "break") return state
      const next = Math.max(0, state.secondsLeft - 1)
      return { secondsLeft: next, lastTickAt: Date.now() }
    }),

  setFocusMinutes: (m) =>
    set((state) => ({
      focusMinutes: m,
      // If pill is idle, mirror the new value into secondsLeft.
      secondsLeft: state.phase === "idle" ? m * 60 : state.secondsLeft,
    })),

  setBreakMinutes: (m) => set({ breakMinutes: m }),

  setSurface: (s) => set({ surface: s }),

  setGoalId: (id) => set({ goalId: id }),

  setMuted: (m) => set({ muted: m }),

  setError: (e) => set({ errorMessage: e }),

  hydrate: (snapshot) =>
    set((state) => ({
      ...state,
      ...snapshot,
    })),
}))
