import { useCallback } from "react"
import type { DocumentListItem } from "@/components/library/types"
import { isDocumentReady } from "@/lib/documentReadiness"
import { useAppStore } from "@/store"

/**
 * Returns a callback that selects a document and updates the readiness pointer.
 *
 * Always sets `activeDocumentId`. If the doc is ready, also sets
 * `lastReadyDocumentId` so the effective-active fallback always points at the
 * user's most recent ready selection. Use this from any place where the user
 * picks a doc (library card click, doc picker, doc-action menu).
 */
export function useSelectDocument(): (doc: DocumentListItem) => void {
  const setActiveDocument = useAppStore((s) => s.setActiveDocument)
  const setLastReadyDocumentId = useAppStore((s) => s.setLastReadyDocumentId)
  return useCallback(
    (doc: DocumentListItem) => {
      setActiveDocument(doc.id)
      if (isDocumentReady(doc)) setLastReadyDocumentId(doc.id)
    },
    [setActiveDocument, setLastReadyDocumentId],
  )
}
