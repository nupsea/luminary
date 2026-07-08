import { create } from "zustand"

// Session-scoped editor chrome state (deliberately NOT persisted): the
// properties rail and split preview reset to defaults on reload.
interface NoteEditorUiState {
  propsRailOpen: boolean
  setPropsRailOpen: (open: boolean) => void
  splitPreview: boolean
  setSplitPreview: (on: boolean) => void
}

export const useNoteEditorUi = create<NoteEditorUiState>((set) => ({
  propsRailOpen: false,
  setPropsRailOpen: (open) => set({ propsRailOpen: open }),
  splitPreview: false,
  setSplitPreview: (on) => set({ splitPreview: on }),
}))
