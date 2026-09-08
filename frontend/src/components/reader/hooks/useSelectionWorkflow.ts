import { useQueryClient } from "@tanstack/react-query"
import { useCallback, useState } from "react"
import { toast } from "sonner"

import { apiPost } from "@/lib/apiClient"
import { docThreadKey, type ChatPreload } from "@/store/chatThreads"

import type { SourceRef } from "../SelectionActionBar"
import type { AnnotationItem, SectionItem } from "../types"

interface UseSelectionWorkflowOpts {
  documentId: string
  sectionMap: Map<string, SectionItem>
  setChatPreload: (preload: ChatPreload) => void
  /** Bring the docked conversation into view; it is already mounted. */
  openAsk: () => void
  /** Bring the docked note composer into view. */
  openNote: () => void
  /** Bring the docked flashcard generator into view. */
  openPractice: () => void
}

// Owns the selection -> {note, flashcard, ask-in-chat, highlight, clip} workflow:
// which docked face is holding the capture, the SelectionActionBar callbacks,
// and what each face is scoped to.
export function useSelectionWorkflow({
  documentId,
  sectionMap,
  setChatPreload,
  openAsk,
  openNote,
  openPractice,
}: UseSelectionWorkflowOpts) {
  const qc = useQueryClient()

  const [noteOpen, setNoteOpen] = useState(false)
  const [noteText, setNoteText] = useState("")
  const [noteSourceRef, setNoteSourceRef] = useState<SourceRef | null>(null)
  const [noteHeading, setNoteHeading] = useState<string | undefined>(undefined)
  // Distinguishes one capture from the next: the composer is docked, so it is
  // still open when a second passage is selected.
  const [noteCaptureId, setNoteCaptureId] = useState(0)

  const [flashcardOpen, setFlashcardOpen] = useState(false)
  const [flashcardText, setFlashcardText] = useState("")
  const [flashcardHeading, setFlashcardHeading] = useState<string | undefined>(undefined)
  // The section the passage sits in. The deck and the run are scoped by id;
  // the heading only names the scope on screen.
  const [flashcardSectionId, setFlashcardSectionId] = useState<string | null>(null)

  const handleAddToNote = useCallback((text: string, sourceRef: SourceRef) => {
    const heading = sourceRef.sectionId ? sectionMap.get(sourceRef.sectionId)?.heading : undefined
    setNoteText(text)
    setNoteSourceRef(sourceRef)
    setNoteHeading(heading)
    setNoteCaptureId((n) => n + 1)
    setNoteOpen(true)
    openNote()
  }, [sectionMap, openNote])

  const handleCreateFlashcard = useCallback((text: string, sourceRef: SourceRef) => {
    const heading = sourceRef.sectionId ? sectionMap.get(sourceRef.sectionId)?.heading : undefined
    setFlashcardText(text)
    setFlashcardHeading(heading)
    setFlashcardSectionId(sourceRef.sectionId ?? null)
    setFlashcardOpen(true)
    openPractice()
  }, [sectionMap, openPractice])

  // Asking about a passage no longer leaves the passage. The question is
  // addressed to this document's own conversation, which is docked beside the
  // text rather than on another tab.
  const handleAskInChat = useCallback((text: string) => {
    setChatPreload({
      text: `Explain this excerpt:\n\n> ${text}`,
      documentId,
      autoSubmit: true,
      threadKey: docThreadKey(documentId),
    })
    openAsk()
  }, [documentId, setChatPreload, openAsk])

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

  return {
    noteOpen,
    noteCaptureId,
    noteText,
    noteSourceRef,
    noteHeading,
    flashcardOpen,
    flashcardText,
    flashcardHeading,
    flashcardSectionId,
    closeNote,
    closeFlashcard,
    handleAddToNote,
    handleCreateFlashcard,
    handleAskInChat,
    handleHighlight,
    handleClip,
  }
}
