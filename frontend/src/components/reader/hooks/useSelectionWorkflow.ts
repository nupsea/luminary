import { useQueryClient } from "@tanstack/react-query"
import { useCallback } from "react"
import { toast } from "sonner"

import { apiPost } from "@/lib/apiClient"
import { docThreadKey, type ChatPreload } from "@/store/chatThreads"

import type { SourceRef } from "../SelectionActionBar"
import { askDraftFor } from "../selectionBarLogic"
import type { AnnotationItem } from "../types"

interface UseSelectionWorkflowOpts {
  documentId: string
  setChatPreload: (preload: ChatPreload) => void
  /** Bring the docked conversation into view; it is already mounted. */
  openAsk: () => void
}

// Owns the selection -> {ask-in-chat, highlight} workflow. Note, Flashcard and
// Clip were each a second way to reach a face that is now docked beside the
// text: a note is written in the Notes face, a deck is scoped in the Practice
// face, and a passage is kept with a swatch.
export function useSelectionWorkflow({
  documentId,
  setChatPreload,
  openAsk,
}: UseSelectionWorkflowOpts) {
  const qc = useQueryClient()

  // The draft lands in this document's docked conversation for the reader to
  // edit and send; it is never sent on their behalf.
  const handleAskInChat = useCallback((text: string) => {
    setChatPreload({
      ...askDraftFor(text),
      documentId,
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

  return {
    handleAskInChat,
    handleHighlight,
  }
}
