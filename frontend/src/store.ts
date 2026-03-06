import { create } from "zustand"

interface AppState {
  activeDocumentId: string | null
  llmMode: "local" | "cloud" | "unavailable"
  libraryView: "grid" | "list"
  notesView: "grid" | "list"
  setActiveDocument: (id: string | null) => void
  setLibraryView: (view: "grid" | "list") => void
  setNotesView: (view: "grid" | "list") => void
}

export const useAppStore = create<AppState>((set) => ({
  activeDocumentId: null,
  llmMode: "local",
  libraryView: "grid",
  notesView: "grid",
  setActiveDocument: (id) => set({ activeDocumentId: id }),
  setLibraryView: (view) => set({ libraryView: view }),
  setNotesView: (view) => set({ notesView: view }),
}))
