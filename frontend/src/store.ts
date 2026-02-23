import { create } from "zustand"

interface AppState {
  activeDocumentId: string | null
  llmMode: "local" | "cloud" | "unavailable"
  setActiveDocument: (id: string | null) => void
}

export const useAppStore = create<AppState>((set) => ({
  activeDocumentId: null,
  llmMode: "local",
  setActiveDocument: (id) => set({ activeDocumentId: id }),
}))
