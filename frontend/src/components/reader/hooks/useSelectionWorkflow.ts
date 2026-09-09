import { useQueryClient } from "@tanstack/react-query"
import { useCallback } from "react"
import { toast } from "sonner"

import { apiPost } from "@/lib/apiClient"
import { docThreadKey, type ChatPreload } from "@/store/chatThreads"

import type { SourceRef } from "../SelectionActionBar"
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

  return {
    handleAskInChat,
    handleHighlight,
  }
}
