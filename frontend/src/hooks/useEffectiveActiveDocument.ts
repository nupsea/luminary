import { useMemo } from "react"
import type { DocumentListItem } from "@/components/library/types"
import { isDocumentReady } from "@/lib/documentReadiness"
import { useAppStore } from "@/store"
import { useReadyDocuments } from "./useReadyDocuments"

interface EffectiveActiveDocumentResult {
  /** Active doc if it is ready, else the most recently ready doc, else null. */
  doc: DocumentListItem | null
  /**
   * The doc id that learning surfaces should treat as active, including before
   * the docs query has resolved. Optimistic: while the docs query is loading
   * we surface `activeDocumentId` so first-paint useState/useQuery hooks see
   * the user's selection instead of null. Only nulled-out once we have
   * positive evidence the active doc isn't ready (and no fallback exists).
   */
  effectiveDocumentId: string | null
  /** Underlying activeDocumentId (may point at an in-progress doc). */
  rawActiveId: string | null
  /** True if the user's chosen active doc is currently in-progress. */
  isFallingBack: boolean
  isLoading: boolean
}

/**
 * Returns the document that learning-feature tabs should treat as "active".
 *
 * Logic:
 *   1. If `activeDocumentId` exists and the corresponding doc is ready → use it.
 *   2. Otherwise fall back to `lastReadyDocumentId` (if still ready in the
 *      latest list). This preserves the user's prior ready doc as the working
 *      default while a new ingestion is mid-flight.
 *   3. Otherwise null. Consumers render an empty state ("Pick a document").
 *
 * The library tab is the only surface that should iterate every doc regardless
 * of readiness; everywhere else should consume this hook.
 */
export function useEffectiveActiveDocument(): EffectiveActiveDocumentResult {
  const activeDocumentId = useAppStore((s) => s.activeDocumentId)
  const lastReadyDocumentId = useAppStore((s) => s.lastReadyDocumentId)
  const { allDocs, readyDocs, isLoading } = useReadyDocuments()

  const result = useMemo<EffectiveActiveDocumentResult>(() => {
    const active = activeDocumentId
      ? allDocs.find((d) => d.id === activeDocumentId) ?? null
      : null
    if (isDocumentReady(active)) {
      return {
        doc: active,
        effectiveDocumentId: active!.id,
        rawActiveId: activeDocumentId,
        isFallingBack: false,
        isLoading,
      }
    }
    // Optimistic path: while the docs query is still loading we don't yet know
    // whether the active doc is ready. Surface `activeDocumentId` so first-
    // paint useState initializers and queries see the user's selection. Once
    // the query resolves the readiness gate above takes over and either keeps
    // the doc or falls back below.
    if (isLoading && activeDocumentId) {
      return {
        doc: null,
        effectiveDocumentId: activeDocumentId,
        rawActiveId: activeDocumentId,
        isFallingBack: false,
        isLoading,
      }
    }
    const fallback = lastReadyDocumentId
      ? readyDocs.find((d) => d.id === lastReadyDocumentId) ?? null
      : null
    if (fallback) {
      return {
        doc: fallback,
        effectiveDocumentId: fallback.id,
        rawActiveId: activeDocumentId,
        isFallingBack: true,
        isLoading,
      }
    }
    // Last-resort: most-recently-accessed ready doc, if any.
    const mostRecent = readyDocs[0] ?? null
    return {
      doc: mostRecent,
      effectiveDocumentId: mostRecent?.id ?? null,
      rawActiveId: activeDocumentId,
      isFallingBack: mostRecent !== null && active !== null && !isDocumentReady(active),
      isLoading,
    }
  }, [activeDocumentId, lastReadyDocumentId, allDocs, readyDocs, isLoading])

  return result
}
