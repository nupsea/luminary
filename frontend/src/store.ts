import { create } from "zustand"
import { persist, createJSONStorage } from "zustand/middleware"

interface StudySectionFilter {
  sectionId: string
  bloomLevelMin: number
}

interface AppState {
  activeDocumentId: string | null
  llmMode: "private" | "cloud" | "hybrid"
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
  // S197: autoSubmit flag triggers immediate send on preload consumption.
  chatPreload: { text: string; documentId: string | null; autoSubmit?: boolean } | null
  // S164: Active collection filter for Notes tab.
  activeCollectionId: string | null
  // S165: Active tag filter for Notes tab (hierarchical prefix match).
  activeTag: string | null
  // S197: Pre-fill new note content from gap analysis "Take a note" action.
  notePreload: { content: string; collectionId?: string } | null
  setNotePreload: (preload: { content: string; collectionId?: string } | null) => void
  // S191: Document filter for Notes tab (set by doc action menu).
  notesDocumentId: string | null
  setNotesDocumentId: (id: string | null) => void
  // Chat persistence
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  chatMessages: any[]
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  setChatMessages: (msgs: any[]) => void
  chatScope: "single" | "all"
  setChatScope: (scope: "single" | "all") => void
  chatSelectedDocId: string | null
  setChatSelectedDocId: (id: string | null) => void
  chatQaError: string | null
  setChatQaError: (err: string | null) => void
  clearChat: () => void
  setActiveDocument: (id: string | null) => void
  setLlmMode: (mode: "private" | "cloud" | "hybrid", provider: string) => void
  setLibraryView: (view: "grid" | "list") => void
  setNotesView: (view: "grid" | "list") => void
  setReviewRemindersEnabled: (enabled: boolean) => void
  setStudySectionFilter: (filter: StudySectionFilter | null) => void
  setChatPreload: (preload: { text: string; documentId: string | null; autoSubmit?: boolean }) => void
  clearChatPreload: () => void
  setActiveCollectionId: (id: string | null) => void
  setActiveTag: (tag: string | null) => void
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
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
      activeTag: null,
      notePreload: null,
      setNotePreload: (preload) => set({ notePreload: preload }),
      notesDocumentId: null,
      setNotesDocumentId: (id) => set({ notesDocumentId: id }),
      chatMessages: [],
      setChatMessages: (msgs) => set({ chatMessages: msgs }),
      chatScope: "all",
      setChatScope: (scope) => set({ chatScope: scope }),
      chatSelectedDocId: null,
      setChatSelectedDocId: (id) => set({ chatSelectedDocId: id }),
      chatQaError: null,
      setChatQaError: (err) => set({ chatQaError: err }),
      clearChat: () => set({ chatMessages: [], chatQaError: null, chatSelectedDocId: null, chatScope: "all" }),
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
      setActiveTag: (tag) => set({ activeTag: tag }),
    }),
    {
      name: "luminary-app-store",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        chatMessages: state.chatMessages,
        chatScope: state.chatScope,
        chatSelectedDocId: state.chatSelectedDocId,
        libraryView: state.libraryView,
        notesView: state.notesView,
        reviewRemindersEnabled: state.reviewRemindersEnabled,
      }),
    }
  )
)
