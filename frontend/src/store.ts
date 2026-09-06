import { EMPTY_THREAD, migrateChatThreads, withThread, type ChatPreload, type ChatThread } from "./store/chatThreads"
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
  // Library left-rail (Filters) open/closed state. Persisted; default closed.
  libraryFiltersOpen: boolean
  notesView: "grid" | "list"
  // Review reminders toggle. Persisted to localStorage; default true (opt-out model).
  // Note: direct localStorage read at module load is safe because Luminary is a client-only
  // SPA (Vite + Tauri) with no server-side rendering.
  reviewRemindersEnabled: boolean
  // Navigate to Study tab filtered to a specific section + bloom level.
  studySectionFilter: StudySectionFilter | null
  // Pre-populate Chat input when user selects "Ask in Chat" from SelectionActionBar.
  // autoSubmit flag triggers immediate send on preload consumption.
  chatPreload: ChatPreload | null
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
  // Conversations, keyed by the surface holding them: the Ask page is
  // PAGE_THREAD, a conversation docked in a reader is docThreadKey(documentId).
  // One global thread would mean docking a second one re-scoped the first.
  chatThreads: Record<string, ChatThread>
  setChatThread: (key: string, patch: Partial<ChatThread>) => void
  clearChatThread: (key: string) => void
  // Sidebar visibility (persisted across reloads).
  chatSidebarOpen: boolean
  setChatSidebarOpen: (open: boolean) => void
  setActiveDocument: (id: string | null) => void
  setLastReadyDocumentId: (id: string | null) => void
  setLlmMode: (mode: "private" | "cloud" | "hybrid", provider: string) => void
  setLibraryView: (view: "grid" | "list") => void
  setLibraryFiltersOpen: (open: boolean) => void
  setNotesView: (view: "grid" | "list") => void
  setReviewRemindersEnabled: (enabled: boolean) => void
  setStudySectionFilter: (filter: StudySectionFilter | null) => void
  setChatPreload: (preload: ChatPreload) => void
  clearChatPreload: () => void
  // The Add Content dialog is app-wide state, not the library page's, because a
  // file can be dropped on any surface. Transient: a File cannot be persisted.
  uploadDialogOpen: boolean
  pendingUpload: File | null
  openUploadDialog: (file?: File) => void
  closeUploadDialog: () => void
  clearPendingUpload: () => void
  setActiveCollectionId: (id: string | null) => void
  setActiveTag: (tag: string | null) => void
  // Transient (not persisted): set before navigating to the reader from a
  // flashcard session so Study.tsx can auto-resume on return.
  pendingStudyResume: { sessionId: string; mode: "flashcard" | "teachback" } | null
  setPendingStudyResume: (r: { sessionId: string; mode: "flashcard" | "teachback" } | null) => void
  // Transient: set before navigating to /study to auto-start a fresh session
  // scoped to the given document (e.g. the reader's "Study" action), so the
  // user lands directly in the session instead of the launcher/dashboard.
  pendingStudyStart: { documentId: string | null; mode: "flashcard" | "teachback" } | null
  setPendingStudyStart: (r: { documentId: string | null; mode: "flashcard" | "teachback" } | null) => void
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      activeDocumentId: null,
      lastReadyDocumentId: null,
      llmMode: "private",
      currentProvider: "openai",
      libraryView: "grid",
      // Open every app start so the rails are visible. Deliberately not persisted.
      libraryFiltersOpen: true,
      notesView: "grid",
      // Only "false" disables; absent key (first run) defaults to enabled.
      reviewRemindersEnabled: localStorage.getItem("luminary:reviewReminders") !== "false",
      studySectionFilter: null,
      chatPreload: null,
      activeCollectionId: null,
      activeTag: null,
      studySessionId: null,
      setStudySessionId: (id) => set({ studySessionId: id }),
      notePreload: null,
      setNotePreload: (preload) => set({ notePreload: preload }),
      notesDocumentId: null,
      setNotesDocumentId: (id) => set({ notesDocumentId: id }),
      chatThreads: {},
      setChatThread: (key, patch) =>
        set((state) => ({ chatThreads: withThread(state.chatThreads, key, patch) })),
      clearChatThread: (key) =>
        set((state) => ({ chatThreads: withThread(state.chatThreads, key, EMPTY_THREAD) })),
      chatSidebarOpen: true,
      setChatSidebarOpen: (open) => set({ chatSidebarOpen: open }),
      setActiveDocument: (id) => set({ activeDocumentId: id }),
      setLastReadyDocumentId: (id) => set({ lastReadyDocumentId: id }),
      setLlmMode: (mode, provider) => set({ llmMode: mode, currentProvider: provider }),
      setLibraryView: (view) => set({ libraryView: view }),
      setLibraryFiltersOpen: (open) => set({ libraryFiltersOpen: open }),
      setNotesView: (view) => set({ notesView: view }),
      setReviewRemindersEnabled: (enabled) => {
        localStorage.setItem("luminary:reviewReminders", String(enabled))
        set({ reviewRemindersEnabled: enabled })
      },
      setStudySectionFilter: (filter) => set({ studySectionFilter: filter }),
      setChatPreload: (preload) => set({ chatPreload: preload }),
      clearChatPreload: () => set({ chatPreload: null }),
      uploadDialogOpen: false,
      pendingUpload: null,
      openUploadDialog: (file) => set({ uploadDialogOpen: true, pendingUpload: file ?? null }),
      closeUploadDialog: () => set({ uploadDialogOpen: false, pendingUpload: null }),
      clearPendingUpload: () => set({ pendingUpload: null }),
      setActiveCollectionId: (id) => set({ activeCollectionId: id }),
      setActiveTag: (tag) => set({ activeTag: tag }),
      pendingStudyResume: null,
      setPendingStudyResume: (r) => set({ pendingStudyResume: r }),
      pendingStudyStart: null,
      setPendingStudyStart: (r) => set({ pendingStudyStart: r }),
    }),
    {
      name: "luminary-app-store",
      storage: createJSONStorage(() => localStorage),
      version: 2,
      // v0 persisted libraryFiltersOpen; hydrating it re-hides the rails.
      // v1 held one conversation in four flat keys; migrateChatThreads folds it
      // into the page thread so an open conversation survives the upgrade.
      migrate: (persisted) => {
        if (persisted && typeof persisted === "object") {
          delete (persisted as Record<string, unknown>).libraryFiltersOpen
          return migrateChatThreads(persisted as Record<string, unknown>) as unknown as AppState
        }
        return persisted as AppState
      },
      partialize: (state) => ({
        chatThreads: state.chatThreads,
        libraryView: state.libraryView,
        notesView: state.notesView,
        reviewRemindersEnabled: state.reviewRemindersEnabled,
        studySessionId: state.studySessionId,
        chatSidebarOpen: state.chatSidebarOpen,
        lastReadyDocumentId: state.lastReadyDocumentId,
      }),
    }
  )
)
