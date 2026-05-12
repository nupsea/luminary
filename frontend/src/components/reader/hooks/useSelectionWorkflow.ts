import { useQueryClient } from "@tanstack/react-query"
import { useCallback, useState } from "react"
import { toast } from "sonner"

import type { Note } from "@/components/NoteEditorDialog"
import { apiPost } from "@/lib/apiClient"

import type { SourceRef } from "../SelectionActionBar"
import type { AnnotationItem, SectionItem } from "../types"

interface UseSelectionWorkflowOpts {
  documentId: string
  sectionMap: Map<string, SectionItem>
  setChatPreload: (preload: { text: string; documentId: string | null; autoSubmit?: boolean }) => void
}

// Owns the selection -> {note, flashcard, ask-in-chat, highlight, clip} workflow:
// dialog open/closed state, the SelectionActionBar callbacks, and the
// post-save handoff to NoteEditorDialog.
export function useSelectionWorkflow({
  documentId,
  sectionMap,
  setChatPreload,
}: UseSelectionWorkflowOpts) {
  const qc = useQueryClient()

  const [noteOpen, setNoteOpen] = useState(false)
  const [noteText, setNoteText] = useState("")
  const [noteSourceRef, setNoteSourceRef] = useState<SourceRef | null>(null)
  const [noteHeading, setNoteHeading] = useState<string | undefined>(undefined)
  const [editingCreatedNote, setEditingCreatedNote] = useState<Note | null>(null)

  const [flashcardOpen, setFlashcardOpen] = useState(false)
  const [flashcardText, setFlashcardText] = useState("")
  const [flashcardSourceRef, setFlashcardSourceRef] = useState<SourceRef | null>(null)
  const [flashcardHeading, setFlashcardHeading] = useState<string | undefined>(undefined)

  const handleAddToNote = useCallback((text: string, sourceRef: SourceRef) => {
    const heading = sourceRef.sectionId ? sectionMap.get(sourceRef.sectionId)?.heading : undefined
    setNoteText(text)
    setNoteSourceRef(sourceRef)
    setNoteHeading(heading)
    setNoteOpen(true)
  }, [sectionMap])

  const handleCreateFlashcard = useCallback((text: string, sourceRef: SourceRef) => {
    const heading = sourceRef.sectionId ? sectionMap.get(sourceRef.sectionId)?.heading : undefined
    setFlashcardText(text)
    setFlashcardSourceRef(sourceRef)
    setFlashcardHeading(heading)
    setFlashcardOpen(true)
  }, [sectionMap])

  const handleAskInChat = useCallback((text: string) => {
    setChatPreload({ text: `Explain this excerpt:\n\n> ${text}`, documentId, autoSubmit: true })
    window.dispatchEvent(new CustomEvent("luminary:navigate", { detail: { tab: "chat" } }))
  }, [documentId, setChatPreload])

  const handleHighlight = useCallback(async (
    text: string,
    sourceRef: SourceRef,
    color: AnnotationItem["color"],
  ) => {
    try {
      await apiPost("/annotations", {
        document_id: documentId,
        section_id: sourceRef.sectionId,
        selected_text: text,
        color,
        page_number: sourceRef.pageNumber,
      })
      void qc.invalidateQueries({ queryKey: ["annotations-for-doc", documentId] })
      toast.success("Highlight saved")
    } catch {
      toast.error("Could not save highlight")
    }
  }, [documentId, qc])

  const handleClip = useCallback(async (text: string, sourceRef: SourceRef) => {
    try {
      await apiPost("/notes", {
        document_id: documentId,
        section_id: sourceRef.sectionId,
        content: `> ${text}`,
        tags: ["clipped"],
      })
      void qc.invalidateQueries({ queryKey: ["notes-for-doc", documentId] })
      toast.success("Clipped to notes")
    } catch {
      toast.error("Could not clip to notes")
    }
  }, [documentId, qc])

  const closeNote = useCallback(() => setNoteOpen(false), [])
  const closeFlashcard = useCallback(() => setFlashcardOpen(false), [])
  const clearEditingCreatedNote = useCallback(() => setEditingCreatedNote(null), [])

  return {
    noteOpen,
    noteText,
    noteSourceRef,
    noteHeading,
    flashcardOpen,
    flashcardText,
    flashcardSourceRef,
    flashcardHeading,
    editingCreatedNote,
    setEditingCreatedNote,
    clearEditingCreatedNote,
    closeNote,
    closeFlashcard,
    handleAddToNote,
    handleCreateFlashcard,
    handleAskInChat,
    handleHighlight,
    handleClip,
  }
}
