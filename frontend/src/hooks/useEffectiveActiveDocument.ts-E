import { useMemo } from "react"
import type { DocumentListItem } from "@/components/library/types"
import {
  type DocumentReadinessShape,
  isDocumentReady,
} from "@/lib/documentReadiness"
import { useAppStore } from "@/store"
import { useReadyDocuments } from "./useReadyDocuments"

interface EffectiveActiveDocumentResult {
  /** Active doc if it passes the readiness predicate, else fallback, else null. */
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

interface Options {
  /**
   * Custom readiness predicate. Defaults to `isDocumentReady`
   * (stage === "complete"). Tabs that can render with partial pipeline
   * output (e.g. Viz only needs Kuzu graph data, populated at the
   * `entity_extract` stage) pass `hasGraphData` instead.
   */
  predicate?: (doc: DocumentReadinessShape | null | undefined) => boolean
}

/**
 * Returns the document that learning-feature tabs should treat as "active".
 *
 * Logic:
 *   1. If `activeDocumentId` exists and the corresponding doc passes the
 *      readiness predicate → use it.
 *   2. Otherwise fall back to `lastReadyDocumentId` (if it still passes the
 *      predicate in the latest list).
 *   3. Otherwise the most-recently-accessed doc that passes the predicate.
 *   4. Otherwise null. Consumers render an empty state ("Pick a document").
 *
 * The library tab is the only surface that should iterate every doc regardless
 * of readiness; everywhere else should consume this hook.
 */
export function useEffectiveActiveDocument(
  options: Options = {},
): EffectiveActiveDocumentResult {
  const { predicate = isDocumentReady } = options
  const activeDocumentId = useAppStore((s) => s.activeDocumentId)
  const lastReadyDocumentId = useAppStore((s) => s.lastReadyDocumentId)
  const { allDocs, isLoading } = useReadyDocuments()

  const result = useMemo<EffectiveActiveDocumentResult>(() => {
    const eligibleDocs = allDocs.filter(predicate)
    const active = activeDocumentId
      ? allDocs.find((d) => d.id === activeDocumentId) ?? null
      : null
    if (predicate(active)) {
      return {
        doc: active,
        effectiveDocumentId: active!.id,
        rawActiveId: activeDocumentId,
        isFallingBack: false,
        isLoading,
      }
    }
    // Optimistic path: surface `activeDocumentId` whenever the user has one
    // selected but we cannot positively confirm it fails the readiness
    // predicate. Two cases land here:
    //   1) The docs query is still loading.
    //   2) The query resolved but `allDocs` does not (yet) contain the
    //      active doc -- e.g. the Viz docs query and useReadyDocuments are
    //      separate caches with their own staleness.
    // Without this path an explicit click on a doc that briefly isn't in
    // `allDocs` collapses to the fallback and the user's choice is lost.
    // Falling back is reserved for the case where we KNOW the active doc
    // exists but fails the predicate (handled below).
    if (activeDocumentId && active === null) {
      return {
        doc: null,
        effectiveDocumentId: activeDocumentId,
        rawActiveId: activeDocumentId,
        isFallingBack: false,
        isLoading,
      }
    }
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
      ? eligibleDocs.find((d) => d.id === lastReadyDocumentId) ?? null
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
    // Last-resort: most-recently-accessed eligible doc, if any.
    const mostRecent = eligibleDocs[0] ?? null
    return {
      doc: mostRecent,
      effectiveDocumentId: mostRecent?.id ?? null,
      rawActiveId: activeDocumentId,
      isFallingBack: mostRecent !== null && active !== null && !predicate(active),
      isLoading,
    }
  }, [activeDocumentId, lastReadyDocumentId, allDocs, predicate, isLoading])

  return result
}
