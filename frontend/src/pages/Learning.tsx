import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BookOpen, BookPlus, Plus, Trash2 } from "lucide-react"
import { useEffect, useState } from "react"
import { useSearchParams } from "react-router-dom"

import { Skeleton } from "@/components/ui/skeleton"
import { DocumentCard } from "@/components/library/DocumentCard"
import { FilterBar } from "@/components/library/FilterBar"
import { IngestingPlaceholder } from "@/components/library/IngestingPlaceholder"
import { SearchBar } from "@/components/library/SearchBar"
import { SortSelect } from "@/components/library/SortSelect"
import { UploadDialog } from "@/components/library/UploadDialog"
import { ViewToggle } from "@/components/library/ViewToggle"
import type { ContentType, SortOption } from "@/components/library/types"
import { DocumentReader } from "@/components/reader/DocumentReader"
import { useSelectDocument } from "@/hooks/useSelectDocument"
import { buildDocActionDetail } from "@/lib/docActionUtils"
import type { DocAction } from "@/lib/docActionUtils"
import { isDocumentReady } from "@/lib/documentReadiness"
import { useAppStore } from "@/store"

import {
  bulkDelete,
  deleteDocument,
  fetchDocuments,
  fetchRecentlyAccessed,
  patchTags,
} from "./Learning/api"
import { LibraryStatsBar } from "./Learning/LibraryStatsBar"
import { LibraryTable } from "./Learning/LibraryTable"
import { SearchPanel } from "./Learning/SearchPanel"
import { WhereToStartPanel } from "./Learning/WhereToStartPanel"

const PAGE_SIZE = 20

function LoadingSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <Skeleton key={i} className="h-28 w-full" />
      ))}
    </div>
  )
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <BookPlus size={48} className="mb-4 text-muted-foreground/50" />
      <h2 className="mb-1 text-lg font-semibold text-foreground">No books yet</h2>
      <p className="mb-6 text-sm text-muted-foreground">
        Ingest a PDF or YouTube video to get started.
      </p>
      <button
        onClick={onAdd}
        className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
      >
        Add your first document
      </button>
    </div>
  )
}

export default function Learning() {
  const activeDocumentId = useAppStore((s) => s.activeDocumentId)
  const setActiveDocument = useAppStore((s) => s.setActiveDocument)
  const selectDocument = useSelectDocument()
  const setChatSelectedDocId = useAppStore((s) => s.setChatSelectedDocId)
  const setChatScope = useAppStore((s) => s.setChatScope)
  const setNotesDocumentId = useAppStore((s) => s.setNotesDocumentId)
  const libraryView = useAppStore((s) => s.libraryView)
  const setLibraryView = useAppStore((s) => s.setLibraryView)
  const queryClient = useQueryClient()

  const [searchParams, setSearchParams] = useSearchParams()
  const tagFilter = searchParams.get("tag")
  // citation deep-link params — doc opens DocumentReader, page sets initial PDF page
  // Capture into state so they survive URL param cleanup (params are cleared after first use
  // but DocumentReader needs them after its async doc fetch completes).
  const docParam = searchParams.get("doc")
  const [savedSectionId, setSavedSectionId] = useState<string | undefined>(
    searchParams.get("section_id") ?? undefined,
  )
  const [savedChunkId, setSavedChunkId] = useState<string | undefined>(
    searchParams.get("chunk_id") ?? undefined,
  )
  const [savedPage, setSavedPage] = useState<number | undefined>(() => {
    const raw = searchParams.get("page")
    if (!raw) return undefined
    const n = parseInt(raw, 10)
    return isNaN(n) ? undefined : n
  })

  const [search, setSearch] = useState("")
  const [selectedTypes, setSelectedTypes] = useState<Set<ContentType>>(new Set())
  const [sort, setSort] = useState<SortOption>("newest")
  const [page, setPage] = useState(1)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [selectMode, setSelectMode] = useState(false)
  const [bulkConfirm, setBulkConfirm] = useState(false)

  const content_type = selectedTypes.size > 0 ? [...selectedTypes].join(",") : undefined

  const { data: pageData, isLoading, isError, isSuccess, refetch } = useQuery({
    queryKey: ["documents", content_type, tagFilter, sort, page, PAGE_SIZE],
    queryFn: () =>
      fetchDocuments({
        content_type,
        tag: tagFilter ?? undefined,
        sort,
        page,
        page_size: PAGE_SIZE,
      }),
    staleTime: 10_000,
    gcTime: 60_000,
  })

  const { data: recentItems } = useQuery({
    queryKey: ["documents-recent"],
    queryFn: fetchRecentlyAccessed,
  })

  const tagsMutation = useMutation({
    mutationFn: ({ id, tags }: { id: string; tags: string[] }) => patchTags(id, tags),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["documents"] })
    },
  })

  const bulkDeleteMutation = useMutation({
    mutationFn: (ids: string[]) => bulkDelete(ids),
    onSuccess: () => {
      setSelectedIds(new Set())
      setSelectMode(false)
      setBulkConfirm(false)
      void queryClient.invalidateQueries({ queryKey: ["documents"] })
      void queryClient.invalidateQueries({ queryKey: ["documents-recent"] })
    },
  })

  const deleteDocumentMutation = useMutation({
    mutationFn: (id: string) => deleteDocument(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["documents"] })
      void queryClient.invalidateQueries({ queryKey: ["documents-recent"] })
    },
  })

  function handleDocumentClick(id: string) {
    // Use the readiness-aware selector so lastReadyDocumentId stays in sync,
    // giving Study/Viz/Chat a sane fallback when active points at an
    // in-progress doc.
    const allKnownDocs = [
      ...(pageData?.items ?? []),
      ...(recentItems ?? []),
    ]
    const doc = allKnownDocs.find((d) => d.id === id)
    if (doc) {
      selectDocument(doc)
    } else {
      setActiveDocument(id)
    }
  }

  // Document action menu handler
  function handleDocAction(docId: string, action: DocAction) {
    if (action === "read") {
      handleDocumentClick(docId)
      return
    }
    if (action === "chat") {
      setChatSelectedDocId(docId)
      setChatScope("single")
    } else if (action === "notes") {
      setNotesDocumentId(docId)
    } else {
      setActiveDocument(docId)
    }
    const detail = buildDocActionDetail(action, docId)
    window.dispatchEvent(new CustomEvent("luminary:navigate", { detail }))
  }

  function handleTagClick(tag: string) {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set("tag", tag)
      return next
    })
    setPage(1)
  }

  function handleTagsChange(id: string, tags: string[]) {
    tagsMutation.mutate({ id, tags })
  }

  function handleContentTypeChange(_id: string, _contentType: ContentType) {
    void queryClient.invalidateQueries({ queryKey: ["documents"] })
    void queryClient.invalidateQueries({ queryKey: ["documents-recent"] })
  }

  function handleSelect(id: string, sel: boolean) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (sel) next.add(id)
      else next.delete(id)
      return next
    })
  }

  function handleSelectAll() {
    const ids = pageData?.items.map((d) => d.id) ?? []
    setSelectedIds(new Set(ids))
  }

  function handleDeselectAll() {
    setSelectedIds(new Set())
  }

  function handleBulkDelete() {
    if (selectedIds.size === 0) return
    setBulkConfirm(true)
  }

  function handleConfirmBulkDelete() {
    bulkDeleteMutation.mutate([...selectedIds])
  }

  function handleDeleteDocument(id: string) {
    deleteDocumentMutation.mutate(id)
  }

  // Reset page when filters change
  function handleTypesChange(types: Set<ContentType>) {
    setSelectedTypes(types)
    setPage(1)
  }

  function handleSortChange(s: SortOption) {
    setSort(s)
    setPage(1)
  }

  // when arriving from a citation deep-link, open the referenced document
  // then clear doc/section_id/page params so the Back button and next doc-open work correctly
  useEffect(() => {
    if (docParam) {
      // Snapshot deep-link params into state before clearing URL
      const sectionId = searchParams.get("section_id") ?? undefined
      const chunkId = searchParams.get("chunk_id") ?? undefined
      const rawPage = searchParams.get("page")
      const pageNum = rawPage ? parseInt(rawPage, 10) : undefined
      setSavedSectionId(sectionId)
      setSavedChunkId(chunkId)
      setSavedPage(pageNum && !isNaN(pageNum) ? pageNum : undefined)

      setActiveDocument(docParam)
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev)
        next.delete("doc")
        next.delete("section_id")
        next.delete("chunk_id")
        next.delete("page")
        return next
      })
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docParam])

  if (activeDocumentId) {
    const allKnownDocs = [
      ...(pageData?.items ?? []),
      ...(recentItems ?? []),
    ]
    const activeDoc = allKnownDocs.find((d) => d.id === activeDocumentId)
    const activeContentType = activeDoc?.content_type ?? ""

    function returnToLibrary() {
      setActiveDocument(null)
      setSavedSectionId(undefined)
      setSavedChunkId(undefined)
      setSavedPage(undefined)
    }

    // Gate the reader on ingestion readiness. If we know the doc from the
    // cached list and it isn't complete, show the IngestingPlaceholder
    // (live progress + cancel/delete) instead of mounting the reader against
    // empty section/chunk/embedding data. Deep-link arrivals where the doc
    // isn't in any cached list fall through to DocumentReader, which renders
    // its own loading state and ultimately surfaces backend errors if any.
    if (activeDoc && !isDocumentReady(activeDoc)) {
      return (
        <IngestingPlaceholder
          documentId={activeDocumentId}
          title={activeDoc.title}
          initialStage={activeDoc.stage}
          onBack={returnToLibrary}
        />
      )
    }

    return (
      <div className="flex h-full flex-col">
        <WhereToStartPanel
          documentId={activeDocumentId}
          contentType={activeContentType}
        />
        <div className="flex-1 min-h-0">
          <DocumentReader
            documentId={activeDocumentId}
            onBack={returnToLibrary}
            initialSectionId={savedSectionId}
            initialChunkId={savedChunkId}
            initialPage={savedPage}
          />
        </div>
      </div>
    )
  }

  const items = pageData?.items ?? []
  const total = pageData?.total ?? 0
  const totalPages = Math.ceil(total / PAGE_SIZE)
  const searchActive = search.trim().length > 0

  return (
    <div className="flex h-full flex-col gap-4 p-6">
      <div className="flex flex-wrap items-center gap-3">
        <SearchBar value={search} onChange={setSearch} />
        {!searchActive && (
          <>
            <SortSelect value={sort} onChange={handleSortChange} />
            <ViewToggle value={libraryView} onChange={setLibraryView} />
          </>
        )}
        <button
          onClick={() => {
            setSelectMode((v) => !v)
            setSelectedIds(new Set())
          }}
          className={`rounded-md border px-3 py-2 text-sm font-medium transition-colors ${
            selectMode
              ? "border-primary bg-primary/10 text-primary"
              : "border-border bg-background text-foreground hover:bg-accent"
          }`}
        >
          Select
        </button>
        <button
          onClick={() => setUploadOpen(true)}
          className="flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          <Plus size={14} />
          Add Content
        </button>
      </div>

      {/* Active filters */}
      {tagFilter && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Filtered by tag:</span>
          <button
            onClick={() => {
              setSearchParams((prev) => {
                const next = new URLSearchParams(prev)
                next.delete("tag")
                return next
              })
              setPage(1)
            }}
            className="flex items-center gap-1 rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary hover:bg-primary/20"
          >
            {tagFilter}
            <span className="ml-0.5">×</span>
          </button>
        </div>
      )}

      {searchActive ? (
        <SearchPanel query={search} onDocumentClick={handleDocumentClick} />
      ) : (
        <>
          <FilterBar selected={selectedTypes} onChange={handleTypesChange} />

          {isLoading && libraryView === "grid" ? (
            <LoadingSkeleton />
          ) : isSuccess && total === 0 && !tagFilter && selectedTypes.size === 0 ? (
            <EmptyState onAdd={() => setUploadOpen(true)} />
          ) : (
            <>
              {/* Bulk select header */}
              {selectMode && (
                <div className="flex items-center gap-3 rounded-lg border border-border bg-muted/50 px-3 py-2 text-sm">
                  <span className="text-muted-foreground">
                    {selectedIds.size} selected
                  </span>
                  <button
                    onClick={handleSelectAll}
                    className="text-primary hover:text-primary/80 text-xs"
                  >
                    Select all
                  </button>
                  <button
                    onClick={handleDeselectAll}
                    className="text-muted-foreground hover:text-foreground text-xs"
                  >
                    Deselect all
                  </button>
                </div>
              )}

              {/* Stats bar -- compact single-row pills */}
              {selectedTypes.size === 0 && !tagFilter && page === 1 && !selectMode && (
                <LibraryStatsBar
                  totalDocuments={total}
                  isDocumentsLoading={isLoading}
                />
              )}

              {/* Continue reading -- single highlighted row for most recently accessed doc */}
              {recentItems && recentItems.length > 0 && selectedTypes.size === 0 && !tagFilter && page === 1 && !selectMode && (
                <div
                  className="flex cursor-pointer select-none items-center gap-3 rounded-lg border border-primary/30 bg-primary/5 px-4 py-3 transition-colors hover:bg-primary/10"
                  onClick={() => handleDocumentClick(recentItems[0].id)}
                >
                  <BookOpen size={15} className="shrink-0 text-primary" />
                  <div className="flex min-w-0 flex-1 flex-col">
                    <span className="text-xs font-semibold uppercase tracking-wide text-primary">
                      Continue reading
                    </span>
                    <span className="truncate text-sm font-medium text-foreground">
                      {recentItems[0].title}
                    </span>
                  </div>
                  {recentItems[0].reading_progress_pct > 0 && (
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {Math.round(recentItems[0].reading_progress_pct * 100)}% read
                    </span>
                  )}
                </div>
              )}

              <section>
                <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {tagFilter
                    ? `Tagged: ${tagFilter}`
                    : selectedTypes.size > 0
                    ? "Results"
                    : "All documents"}
                  {total > 0 && (
                    <span className="ml-2 font-normal normal-case text-muted-foreground/60">
                      ({total})
                    </span>
                  )}
                </h2>
                {libraryView === "list" ? (
                  <LibraryTable
                    items={items}
                    isLoading={isLoading}
                    isError={isError}
                    onRowClick={handleDocumentClick}
                    onRetry={() => void refetch()}
                  />
                ) : isError ? (
                  <div className="flex items-center gap-3 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                    <span className="flex-1">Could not load library. Check that the backend is running.</span>
                    <button
                      onClick={() => void refetch()}
                      className="rounded border border-amber-300 bg-white px-3 py-1 text-xs text-amber-700 hover:bg-amber-50"
                    >
                      Retry
                    </button>
                  </div>
                ) : items.length === 0 ? (
                  <p className="py-8 text-center text-sm text-muted-foreground">
                    {tagFilter
                      ? `No documents tagged "${tagFilter}".`
                      : "No documents match your filters."}
                  </p>
                ) : (
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                    {items.map((doc) => (
                      <DocumentCard
                        key={doc.id}
                        doc={doc}
                        onClick={handleDocumentClick}
                        onTagClick={handleTagClick}
                        onTagsChange={handleTagsChange}
                        onDelete={!selectMode ? handleDeleteDocument : undefined}
                        onContentTypeChange={handleContentTypeChange}
                        onAction={handleDocAction}
                        selected={selectedIds.has(doc.id)}
                        onSelect={selectMode ? handleSelect : undefined}
                      />
                    ))}
                  </div>
                )}
              </section>

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="flex items-center justify-center gap-2 pt-2">
                  <button
                    disabled={page === 1}
                    onClick={() => setPage((p) => p - 1)}
                    className="rounded-md border border-border px-3 py-1.5 text-sm disabled:opacity-40 hover:bg-accent"
                  >
                    Prev
                  </button>
                  <span className="text-sm text-muted-foreground">
                    {page} / {totalPages}
                  </span>
                  <button
                    disabled={page >= totalPages}
                    onClick={() => setPage((p) => p + 1)}
                    className="rounded-md border border-border px-3 py-1.5 text-sm disabled:opacity-40 hover:bg-accent"
                  >
                    Next
                  </button>
                </div>
              )}
            </>
          )}
        </>
      )}

      {/* Bulk action bar */}
      {selectMode && selectedIds.size > 0 && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 rounded-xl border border-border bg-card px-5 py-3 shadow-lg">
          <span className="text-sm font-medium">{selectedIds.size} selected</span>
          <button
            onClick={handleBulkDelete}
            className="flex items-center gap-1.5 rounded-md bg-destructive px-3 py-1.5 text-sm font-medium text-destructive-foreground hover:bg-destructive/90"
          >
            <Trash2 size={13} />
            Delete ({selectedIds.size})
          </button>
        </div>
      )}

      {/* Bulk delete confirmation */}
      {bulkConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-80 rounded-xl border border-border bg-card p-6 shadow-xl">
            <h3 className="mb-2 text-base font-semibold">Delete {selectedIds.size} document{selectedIds.size !== 1 ? "s" : ""}?</h3>
            <p className="mb-5 text-sm text-muted-foreground">
              This action cannot be undone. All related data (chunks, flashcards, summaries) will
              be permanently deleted.
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setBulkConfirm(false)}
                className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmBulkDelete}
                disabled={bulkDeleteMutation.isPending}
                className="rounded-md bg-destructive px-3 py-1.5 text-sm font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-60"
              >
                {bulkDeleteMutation.isPending ? "Deleting..." : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}

      <UploadDialog open={uploadOpen} onClose={() => setUploadOpen(false)} />
    </div>
  )
}
