import { create } from "zustand"

interface AppState {
  activeDocumentId: string | null
  llmMode: "private" | "cloud"
  currentProvider: string
  libraryView: "grid" | "list"
  notesView: "grid" | "list"
  setActiveDocument: (id: string | null) => void
  setLlmMode: (mode: "private" | "cloud", provider: string) => void
  setLibraryView: (view: "grid" | "list") => void
  setNotesView: (view: "grid" | "list") => void
}

export const useAppStore = create<AppState>((set) => ({
  activeDocumentId: null,
  llmMode: "private",
  currentProvider: "openai",
  libraryView: "grid",
  notesView: "grid",
  setActiveDocument: (id) => set({ activeDocumentId: id }),
  setLlmMode: (mode, provider) => set({ llmMode: mode, currentProvider: provider }),
  setLibraryView: (view) => set({ libraryView: view }),
  setNotesView: (view) => set({ notesView: view }),
}))
