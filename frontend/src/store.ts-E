import { create } from "zustand"
import { persist, createJSONStorage } from "zustand/middleware"

interface StudySectionFilter {
  sectionId: string
  bloomLevelMin: number
}

interface AppState {
  activeDocumentId: string | null
  // Most recently *ready* (stage === "complete") document the user activated.
  // Tabs that need a default ready doc (Study, Viz, Chat) fall back to this
  // when activeDocumentId points at an in-progress ingestion. Persisted so the
  // user's last good doc is restored across reloads.
  lastReadyDocumentId: string | null
  llmMode: "private" | "cloud" | "hybrid"
  currentProvider: string
  libraryView: "grid" | "list"
  notesView: "grid" | "list"
  // Review reminders toggle. Persisted to localStorage; default true (opt-out model).
  // Note: direct localStorage read at module load is safe because Luminary is a client-only
  // SPA (Vite + Tauri) with no server-side rendering.
  reviewRemindersEnabled: boolean
  // Navigate to Study tab filtered to a specific section + bloom level.
  studySectionFilter: StudySectionFilter | null
  // Pre-populate Chat input when user selects "Ask in Chat" from SelectionActionBar.
  // autoSubmit flag triggers immediate send on preload consumption.
  chatPreload: { text: string; documentId: string | null; autoSubmit?: boolean } | null
  // Global sliding chat panel state
  chatPanelOpen: boolean
  setChatPanelOpen: (open: boolean) => void
  // Active collection filter for Notes tab.
  activeCollectionId: string | null
  // Active tag filter for Notes tab (hierarchical prefix match).
  activeTag: string | null
  // Pre-fill new note content from gap analysis "Take a note" action.
  notePreload: { content: string; collectionId?: string } | null
  setNotePreload: (preload: { content: string; collectionId?: string } | null) => void
  // Persisted study session ID for teach-back results across tab switches
  studySessionId: string | null
  setStudySessionId: (id: string | null) => void
  // Document filter for Notes tab (set by doc action menu).
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
  // Persisted chat session id; null means "no session yet, will be created on first send".
  activeChatSessionId: string | null
  setActiveChatSessionId: (id: string | null) => void
  // Sidebar visibility (persisted across reloads).
  chatSidebarOpen: boolean
  setChatSidebarOpen: (open: boolean) => void
  clearChat: () => void
  setActiveDocument: (id: string | null) => void
  setLastReadyDocumentId: (id: string | null) => void
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
      lastReadyDocumentId: null,
      llmMode: "private",
      currentProvider: "openai",
      libraryView: "grid",
      notesView: "grid",
      // Only "false" disables; absent key (first run) defaults to enabled.
      reviewRemindersEnabled: localStorage.getItem("luminary:reviewReminders") !== "false",
      studySectionFilter: null,
      chatPreload: null,
      chatPanelOpen: false,
      setChatPanelOpen: (open) => set({ chatPanelOpen: open }),
      activeCollectionId: null,
      activeTag: null,
      studySessionId: null,
      setStudySessionId: (id) => set({ studySessionId: id }),
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
      activeChatSessionId: null,
      setActiveChatSessionId: (id) => set({ activeChatSessionId: id }),
      chatSidebarOpen: true,
      setChatSidebarOpen: (open) => set({ chatSidebarOpen: open }),
      clearChat: () => set({ chatMessages: [], chatQaError: null, chatSelectedDocId: null, chatScope: "all", activeChatSessionId: null }),
      setActiveDocument: (id) => set({ activeDocumentId: id }),
      setLastReadyDocumentId: (id) => set({ lastReadyDocumentId: id }),
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
        studySessionId: state.studySessionId,
        activeChatSessionId: state.activeChatSessionId,
        chatSidebarOpen: state.chatSidebarOpen,
        lastReadyDocumentId: state.lastReadyDocumentId,
      }),
    }
  )
)
