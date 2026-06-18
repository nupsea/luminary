// launcherStore -- Study Launcher state (docs/study-launcher.md).
// Holds the open scope + chosen mode/length, fetches an honest preview (commit=false),
// and starts a Study Event (commit=true). API calls live here; the component stays thin.

import { create } from "zustand"
import { apiPost } from "@/lib/apiClient"
import { logger } from "@/lib/logger"
import type { StudyScope } from "@/lib/studyLauncher"

export type StudyMode = "quick_quiz" | "full_session" | "drill"

export interface AssemblePreview {
  due_count: number
  generated_count: number
  mapped_count: number
  unmapped_count: number
  topic_mix: string[]
  thin_scope_warning: string | null
}

export interface AssembleResponse {
  event_id: string
  scope_type: string
  scope_ref: string | null
  mode: string
  concept_ids: string[]
  cards: unknown[]
  preview: AssemblePreview
  teachback_available: boolean
}

interface AssembleBody {
  scope_type: string
  scope_ref?: string
  mode: StudyMode
  length_min: number
  commit: boolean
}

interface LauncherState {
  open: boolean
  scope: StudyScope | null
  mode: StudyMode
  lengthMin: number
  loading: boolean
  starting: boolean
  error: string | null
  preview: AssemblePreview | null
  teachbackAvailable: boolean

  openWith: (scope: StudyScope) => void
  close: () => void
  setMode: (mode: StudyMode) => void
  setLength: (lengthMin: number) => void
  refreshPreview: () => Promise<void>
  start: () => Promise<AssembleResponse | null>
}

function bodyOf(state: LauncherState, commit: boolean): AssembleBody | null {
  if (!state.scope) return null
  return {
    scope_type: state.scope.type,
    scope_ref: state.scope.ref,
    mode: state.mode,
    length_min: state.lengthMin,
    commit,
  }
}

export const useLauncherStore = create<LauncherState>((set, get) => ({
  open: false,
  scope: null,
  mode: "quick_quiz",
  lengthMin: 5,
  loading: false,
  starting: false,
  error: null,
  preview: null,
  teachbackAvailable: false,

  openWith: (scope) => {
    set({
      open: true,
      scope,
      mode: "quick_quiz",
      lengthMin: 5,
      preview: null,
      error: null,
      teachbackAvailable: false,
    })
    void get().refreshPreview()
  },

  close: () => set({ open: false, scope: null, preview: null, error: null }),

  setMode: (mode) => {
    set({ mode })
    void get().refreshPreview()
  },

  setLength: (lengthMin) => {
    set({ lengthMin })
    void get().refreshPreview()
  },

  refreshPreview: async () => {
    const body = bodyOf(get(), false)
    if (!body) return
    set({ loading: true, error: null })
    try {
      const res = await apiPost<AssembleResponse>("/study/assemble", body)
      set({
        preview: res.preview,
        teachbackAvailable: res.teachback_available,
        loading: false,
      })
    } catch (err) {
      logger.warn("[launcher] preview failed", { err })
      set({ loading: false, error: "Couldn't preview this scope. You can still start." })
    }
  },

  start: async () => {
    const body = bodyOf(get(), true)
    if (!body) return null
    set({ starting: true, error: null })
    try {
      const res = await apiPost<AssembleResponse>("/study/assemble", body)
      set({ starting: false, open: false, scope: null, preview: null })
      return res
    } catch (err) {
      logger.warn("[launcher] start failed", { err })
      set({ starting: false, error: "Couldn't start the session. Try again." })
      return null
    }
  },
}))
