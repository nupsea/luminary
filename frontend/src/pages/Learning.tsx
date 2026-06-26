import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BookPlus, Plus, SlidersHorizontal, Trash2 } from "lucide-react"
import { useEffect, useState } from "react"
import { useSearchParams, useLocation } from "react-router-dom"
import { toast } from "sonner"

import { Skeleton } from "@/components/ui/skeleton"
import { DocumentCard } from "@/components/library/DocumentCard"
import { FilterBar } from "@/components/library/FilterBar"
import { LibraryCollectionsRail } from "@/components/library/LibraryCollectionsRail"
import { LibraryTagRail } from "@/components/library/LibraryTagRail"
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
import { apiGet } from "@/lib/apiClient"
import { useAppStore } from "@/store"

import {
  bulkDelete,
  deleteDocument,
  fetchDocuments,
  fetchRecentlyAccessed,
} from "./Learning/api"
import { LibraryStatsBar } from "./Learning/LibraryStatsBar"
import { LibraryTable } from "./Learning/LibraryTable"
import { SearchPanel } from "./Learning/SearchPanel"
import { TodayHero } from "./Learning/TodayHero"
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
        Add a PDF or YouTube video to get started.
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
  const libraryFiltersOpen = useAppStore((s) => s.libraryFiltersOpen)
  const setLibraryFiltersOpen = useAppStore((s) => s.setLibraryFiltersOpen)
  // Seed the Library's collection filter from the global activeCollectionId
  // when arriving from the collection workspace (or anywhere else that sets
  // the store). Then clear the store so a later return to /library without
  // a fresh selection doesn't reapply the old filter.
  const incomingCollectionId = useAppStore((s) => s.activeCollectionId)
  const clearActiveCollectionId = useAppStore((s) => s.setActiveCollectionId)
  const queryClient = useQueryClient()

  const [searchParams, setSearchParams] = useSearchParams()
  const routeLocation = useLocation()
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
  const [selectedCollectionId, setSelectedCollectionId] = useState<string | null>(
    incomingCollectionId ?? null,
  )
  // Consume the store value once on mount so a subsequent visit to /library
  // (e.g. via the sidebar tab) lands unfiltered. The local selectedCollectionId
  // remains the source of truth from here on.
  useEffect(() => {
    if (incomingCollectionId) clearActiveCollectionId(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const [uploadOpen, setUploadOpen] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [selectMode, setSelectMode] = useState(false)
  const [bulkConfirm, setBulkConfirm] = useState(false)

  const content_type = selectedTypes.size > 0 ? [...selectedTypes].join(",") : undefined

  // Fetch the active collection's name + color so the chip in the active-
  // filter row can render legibly (slug != display name; users named it).
  const { data: activeCollectionMeta } = useQuery({
    queryKey: ["collection-meta", selectedCollectionId],
    queryFn: () =>
      apiGet<{ id: string; name: string; color: string }>(
        `/collections/${selectedCollectionId}`,
      ),
    enabled: !!selectedCollectionId,
    staleTime: 60_000,
  })

  const { data: pageData, isLoading, isError, isSuccess, refetch } = useQuery({
    queryKey: ["documents", content_type, tagFilter, selectedCollectionId, sort, page, PAGE_SIZE],
    queryFn: () =>
      fetchDocuments({
        content_type,
        tag: tagFilter ?? undefined,
        collection_id: selectedCollectionId ?? undefined,
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

  const bulkDeleteMutation = useMutation({
    mutationFn: (ids: string[]) => bulkDelete(ids),
    onSuccess: (_data, ids) => {
      setSelectedIds(new Set())
      setSelectMode(false)
      setBulkConfirm(false)
      void queryClient.invalidateQueries({ queryKey: ["documents"] })
      void queryClient.invalidateQueries({ queryKey: ["documents-recent"] })
      toast.success(`Deleted ${ids.length} document${ids.length === 1 ? "" : "s"}`)
    },
    onError: () => toast.error("Failed to delete documents. Please try again."),
  })

  const deleteDocumentMutation = useMutation({
    mutationFn: (id: string) => deleteDocument(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["documents"] })
      void queryClient.invalidateQueries({ queryKey: ["documents-recent"] })
      toast.success("Document deleted")
    },
    onError: () => toast.error("Failed to delete document. Please try again."),
  })

  // Card click now routes to the Doc overview (no surprise-session;
  // Clicking a document opens the reader directly (the study/generate/chat actions live in the
  // reader header now, in the doc's context -- no intermediate overview page).
  function handleDocumentClick(id: string) {
    openReader(id)
  }

  function openReader(id: string) {
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
      openReader(docId)
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

  function handleCollectionSelect(id: string | null) {
    setSelectedCollectionId(id)
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
      }, { replace: true, state: routeLocation.state })
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
            <button
              onClick={() => setLibraryFiltersOpen(!libraryFiltersOpen)}
              className={`flex items-center gap-1.5 rounded-md border px-3 py-2 text-sm font-medium transition-colors ${
                libraryFiltersOpen
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border bg-background text-foreground hover:bg-accent"
              }`}
              title={libraryFiltersOpen ? "Hide filters" : "Show filters"}
            >
              <SlidersHorizontal size={14} />
              Filters
              {(() => {
                const active = (selectedCollectionId ? 1 : 0) + (tagFilter ? 1 : 0)
                return active > 0 ? (
                  <span className="ml-0.5 rounded-full bg-primary/20 px-1.5 text-[10px] font-semibold text-primary">
                    {active}
                  </span>
                ) : null
              })()}
            </button>
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

      {/* Active filters -- always rendered when anything is active so the
          collection/tag selection is obvious without opening the filter rail.
          Each chip is clickable to clear; "Clear all" appears once both
          dimensions are filled. */}
      {(tagFilter || selectedCollectionId) && (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-primary/30 bg-primary/5 px-3 py-2">
          <span className="text-xs font-medium uppercase tracking-wide text-primary/80">
            Filtered:
          </span>
          {selectedCollectionId && (
            <button
              onClick={() => handleCollectionSelect(null)}
              className="flex items-center gap-1.5 rounded-full bg-background px-2.5 py-0.5 text-xs font-medium text-foreground hover:bg-accent ring-1 ring-border"
              title="Clear collection filter"
            >
              <span
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ backgroundColor: activeCollectionMeta?.color ?? "#888" }}
              />
              <span className="truncate max-w-[14rem]">
                {activeCollectionMeta?.name ?? "Collection"}
              </span>
              <span className="text-muted-foreground">×</span>
            </button>
          )}
          {tagFilter && (
            <button
              onClick={() => {
                setSearchParams((prev) => {
                  const next = new URLSearchParams(prev)
                  next.delete("tag")
                  return next
                })
                setPage(1)
              }}
              className="flex items-center gap-1.5 rounded-full bg-background px-2.5 py-0.5 text-xs font-medium text-foreground hover:bg-accent ring-1 ring-border"
              title="Clear tag filter"
            >
              <span className="text-muted-foreground">#</span>
              <span className="truncate max-w-[14rem]">{tagFilter}</span>
              <span className="text-muted-foreground">×</span>
            </button>
          )}
          {tagFilter && selectedCollectionId && (
            <button
              onClick={() => {
                handleCollectionSelect(null)
                setSearchParams((prev) => {
                  const next = new URLSearchParams(prev)
                  next.delete("tag")
                  return next
                })
                setPage(1)
              }}
              className="ml-auto text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
            >
              Clear all
            </button>
          )}
        </div>
      )}

      {searchActive ? (
        <SearchPanel query={search} onDocumentClick={handleDocumentClick} />
      ) : (
        <div className={libraryFiltersOpen ? "flex gap-4 items-start" : "contents"}>
          {libraryFiltersOpen && (
            <div className="flex w-56 shrink-0 flex-col gap-3">
              <LibraryCollectionsRail
                selectedId={selectedCollectionId}
                onSelect={handleCollectionSelect}
              />
              <LibraryTagRail
                activeTag={tagFilter}
                onSelect={(tag) => {
                  setSearchParams((prev) => {
                    const next = new URLSearchParams(prev)
                    if (tag) next.set("tag", tag)
                    else next.delete("tag")
                    return next
                  })
                  setPage(1)
                }}
              />
            </div>
          )}
          <div className={libraryFiltersOpen ? "flex-1 min-w-0 flex flex-col gap-4" : "contents"}>
          <FilterBar selected={selectedTypes} onChange={handleTypesChange} />

          {isLoading && libraryView === "grid" ? (
            <LoadingSkeleton />
          ) : isSuccess && total === 0 && !tagFilter && selectedTypes.size === 0 && !selectedCollectionId ? (
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

              {/* Today hero -- surfaces highest-leverage action: due cards (recall)
                  beats continue-reading (reception). Hides when no cards due AND no recent doc. */}
              {selectedTypes.size === 0 && !tagFilter && page === 1 && !selectMode && (
                <TodayHero
                  recentItem={recentItems?.[0]}
                  onContinue={openReader}
                />
              )}

              <section>
                <h2 className="lum-eyebrow mb-2">
                  {tagFilter
                    ? `Tagged: ${tagFilter}`
                    : selectedCollectionId
                    ? "In collection"
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
                  <div className="py-8 text-center text-sm text-muted-foreground">
                    {tagFilter ? (
                      <p>No documents tagged &ldquo;{tagFilter}&rdquo;.</p>
                    ) : selectedCollectionId ? (
                      <>
                        <p>No documents in this collection yet.</p>
                        <p className="mt-1 text-xs text-muted-foreground/80">
                          Add one from any DocumentCard&apos;s <span className="font-semibold">⋯</span> menu, or drag a card onto the collection in the rail.
                        </p>
                      </>
                    ) : (
                      <p>No documents match your filters.</p>
                    )}
                  </div>
                ) : (
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                    {items.map((doc) => (
                      <DocumentCard
                        key={doc.id}
                        doc={doc}
                        onClick={handleDocumentClick}
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
          </div>
        </div>
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
