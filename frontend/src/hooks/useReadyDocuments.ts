import { useQuery } from "@tanstack/react-query"
import { useMemo } from "react"
import { API_BASE } from "@/lib/config"
import { isDocumentReady } from "@/lib/documentReadiness"
import type { DocumentListItem, DocumentListResponse } from "@/components/library/types"

const READY_PAGE_SIZE = 200

async function fetchAllDocuments(): Promise<DocumentListItem[]> {
  const res = await fetch(
    `${API_BASE}/documents?sort=last_accessed&page=1&page_size=${READY_PAGE_SIZE}`,
  )
  if (!res.ok) throw new Error("Failed to load documents")
  const data = (await res.json()) as DocumentListResponse
  return data.items
}

interface ReadyDocumentsResult {
  allDocs: DocumentListItem[]
  readyDocs: DocumentListItem[]
  isLoading: boolean
  isError: boolean
}

/**
 * Single-source documents query that exposes ready and all-docs slices.
 *
 * Tabs that drive learning features (Study, Viz, Chat, Notes filters) should
 * consume `readyDocs` so in-progress ingestions never appear as selectable
 * sources. The library is the only surface that should iterate `allDocs`.
 *
 * Sorted by last_accessed so the "most recently used ready doc" comes first
 * — that's what the effective-active-doc fallback uses when the current
 * active doc isn't ready.
 */
export function useReadyDocuments(): ReadyDocumentsResult {
  const query = useQuery({
    queryKey: ["documents", "ready-feed"],
    queryFn: fetchAllDocuments,
    // Same staleness window as the library list. IngestionTrackerProvider
    // invalidates ["documents"] on stage transitions, which cascades here.
    staleTime: 10_000,
  })

  const allDocs = useMemo(() => query.data ?? [], [query.data])
  const readyDocs = useMemo(() => allDocs.filter(isDocumentReady), [allDocs])

  return {
    allDocs,
    readyDocs,
    isLoading: query.isLoading,
    isError: query.isError,
  }
}
