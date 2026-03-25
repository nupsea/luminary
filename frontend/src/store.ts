import { create } from "zustand"

interface StudySectionFilter {
  sectionId: string
  bloomLevelMin: number
}

interface AppState {
  activeDocumentId: string | null
  llmMode: "private" | "cloud"
  currentProvider: string
  libraryView: "grid" | "list"
  notesView: "grid" | "list"
  // S118: Review reminders toggle. Persisted to localStorage; default true (opt-out model).
  // Note: direct localStorage read at module load is safe because Luminary is a client-only
  // SPA (Vite + Tauri) with no server-side rendering.
  reviewRemindersEnabled: boolean
  // S143: Navigate to Study tab filtered to a specific section + bloom level.
  studySectionFilter: StudySectionFilter | null
  // S147: Pre-populate Chat input when user selects "Ask in Chat" from SelectionActionBar.
  chatPreload: { text: string; documentId: string | null } | null
  // S164: Active collection filter for Notes tab.
  activeCollectionId: string | null
  setActiveDocument: (id: string | null) => void
  setLlmMode: (mode: "private" | "cloud", provider: string) => void
  setLibraryView: (view: "grid" | "list") => void
  setNotesView: (view: "grid" | "list") => void
  setReviewRemindersEnabled: (enabled: boolean) => void
  setStudySectionFilter: (filter: StudySectionFilter | null) => void
  setChatPreload: (preload: { text: string; documentId: string | null }) => void
  clearChatPreload: () => void
  setActiveCollectionId: (id: string | null) => void
}

export const useAppStore = create<AppState>((set) => ({
  activeDocumentId: null,
  llmMode: "private",
  currentProvider: "openai",
  libraryView: "grid",
  notesView: "grid",
  // Only "false" disables; absent key (first run) defaults to enabled.
  reviewRemindersEnabled: localStorage.getItem("luminary:reviewReminders") !== "false",
  studySectionFilter: null,
  chatPreload: null,
  activeCollectionId: null,
  setActiveDocument: (id) => set({ activeDocumentId: id }),
  setLlmMode: (mode, provider) => set({ llmMode: mode, currentProvider: provider }),
  setLibraryView: (view) => set({ libraryView: view }),
  setNotesView: (view) => set({ notesView: view }),
  setReviewRemindersEnabled: (enabled) => {
    localStorage.setItem("luminary:reviewReminders", String(enabled))
    set({ reviewRemindersEnabled: enabled })
  },
  setStudySectionFilter: (filter) => set({ studySectionFilter: filter }),
  setChatPreload: (preload) => set({ chatPreload: preload }),
  clearChatPreload: () => set({ chatPreload: null }),
  setActiveCollectionId: (id) => set({ activeCollectionId: id }),
}))
