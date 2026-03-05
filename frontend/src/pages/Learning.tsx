import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BookPlus, ChevronDown, FileText, Loader2, Plus, RefreshCw, Trash2 } from "lucide-react"
import { useEffect, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { cn } from "@/lib/utils"
import { Skeleton } from "@/components/ui/skeleton"
import { FilterBar } from "@/components/library/FilterBar"
import { SearchBar } from "@/components/library/SearchBar"
import { SortSelect } from "@/components/library/SortSelect"
import { UploadDialog } from "@/components/library/UploadDialog"
import { ViewToggle } from "@/components/library/ViewToggle"
import { DocumentCard } from "@/components/library/DocumentCard"
import { DocumentRow } from "@/components/library/DocumentRow"
import type {
  ContentType,
  DocumentListItem,
  DocumentListResponse,
  SortOption,
  ViewMode,
} from "@/components/library/types"
import { DocumentReader } from "@/components/reader/DocumentReader"
import { useDebounce } from "@/hooks/useDebounce"
import { useAppStore } from "@/store"

const API_BASE = "http://localhost:8000"
const PAGE_SIZE = 20

interface SearchMatch {
  chunk_id: string
  document_id: string
  document_title: string
  content_type: string
  section_heading: string
  page: number
  text_excerpt: string
  relevance_score: number
}

interface DocumentGroup {
  document_id: string
  document_title: string
  content_type: string
  matches: SearchMatch[]
}

async function fetchSearch(q: string, contentTypes: string): Promise<DocumentGroup[]> {
  const params = new URLSearchParams({ q, limit: "30" })
  if (contentTypes) params.set("content_types", contentTypes)
  const res = await fetch(`${API_BASE}/search?${params.toString()}`)
  if (!res.ok) return []
  const data = (await res.json()) as { results: DocumentGroup[] }
  return data.results
}

async function fetchDocuments(params: {
  content_type?: string
  tag?: string
  sort: SortOption
  page: number
  page_size: number
}): Promise<DocumentListResponse> {
  const p = new URLSearchParams({
    sort: params.sort,
    page: String(params.page),
    page_size: String(params.page_size),
  })
  if (params.content_type) p.set("content_type", params.content_type)
  if (params.tag) p.set("tag", params.tag)
  const res = await fetch(`${API_BASE}/documents?${p.toString()}`)
  if (!res.ok) throw new Error("Failed to fetch documents")
  return res.json() as Promise<DocumentListResponse>
}

async function fetchRecentlyAccessed(): Promise<DocumentListItem[]> {
  const res = await fetch(`${API_BASE}/documents?sort=last_accessed&page_size=5`)
  if (!res.ok) return []
  const data = (await res.json()) as DocumentListResponse
  return data.items
}

async function patchTags(id: string, tags: string[]): Promise<void> {
  await fetch(`${API_BASE}/documents/${id}/tags`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tags }),
  })
}

async function bulkDelete(ids: string[]): Promise<void> {
  await fetch(`${API_BASE}/documents/bulk-delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  })
}

async function deleteDocument(id: string): Promise<void> {
  await fetch(`${API_BASE}/documents/${id}`, { method: "DELETE" })
}

// ---------------------------------------------------------------------------
// LibraryOverview — holistic summary across all ingested documents
// ---------------------------------------------------------------------------

type LibraryOverviewMode = "one_sentence" | "executive" | "detailed"

const LIBRARY_MODES: { mode: LibraryOverviewMode; label: string }[] = [
  { mode: "one_sentence", label: "One sentence" },
  { mode: "executive", label: "Key themes" },
  { mode: "detailed", label: "Detailed" },
]

function LibraryOverview() {
  const [activeMode, setActiveMode] = useState<LibraryOverviewMode>("executive")
  const [summaries, setSummaries] = useState<Partial<Record<LibraryOverviewMode, string>>>({})
  const [streaming, setStreaming] = useState<Partial<Record<LibraryOverviewMode, boolean>>>({})
  const [error, setError] = useState<string | null>(null)
  const [notEnough, setNotEnough] = useState(false)
  const [collapsed, setCollapsed] = useState(false)

  async function generate(mode: LibraryOverviewMode) {
    setError(null)
    setNotEnough(false)
    setStreaming((s) => ({ ...s, [mode]: true }))
    setSummaries((s) => ({ ...s, [mode]: "" }))
    try {
      const res = await fetch(`${API_BASE}/summarize/all`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, model: null }),
      })
      if (!res.ok || !res.body) throw new Error("Failed")
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n")
        buffer = lines.pop() ?? ""
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const payload = JSON.parse(line.slice(6)) as Record<string, unknown>
              if (typeof payload["token"] === "string") {
                setSummaries((s) => ({ ...s, [mode]: (s[mode] ?? "") + payload["token"] }))
              }
              if (payload["error"] === "not_enough_summaries") {
                setNotEnough(true)
                setStreaming((s) => ({ ...s, [mode]: false }))
              } else if (payload["error"] === "llm_unavailable") {
                setError(
                  typeof payload["message"] === "string"
                    ? payload["message"]
                    : "Ollama is not running. Start it with: ollama serve",
                )
                setStreaming((s) => ({ ...s, [mode]: false }))
              }
              if (payload["done"] === true) {
                setStreaming((s) => ({ ...s, [mode]: false }))
              }
            } catch {
              // skip malformed SSE event
            }
          }
        }
      }
    } catch {
      setStreaming((s) => ({ ...s, [mode]: false }))
      setError("Failed to generate library overview.")
    }
  }

  const currentSummary = summaries[activeMode]
  const isStreaming = streaming[activeMode] ?? false

  return (
    <div className="rounded-lg border border-border bg-card">
      <button
        onClick={() => setCollapsed((v) => !v)}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
      >
        <span className="text-sm font-semibold text-foreground">Library Overview</span>
        <ChevronDown
          size={14}
          className={cn(
            "text-muted-foreground transition-transform",
            collapsed && "-rotate-90",
          )}
        />
      </button>
      {!collapsed && (
        <div className="border-t border-border px-4 pb-4 pt-3">
          {/* Mode tabs */}
          <div className="mb-3 flex gap-1 rounded-md bg-muted p-1">
            {LIBRARY_MODES.map((m) => (
              <button
                key={m.mode}
                onClick={() => setActiveMode(m.mode)}
                className={cn(
                  "flex-1 rounded py-1.5 text-xs font-medium transition-colors",
                  activeMode === m.mode
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {m.label}
              </button>
            ))}
          </div>
          {/* Content */}
          {error && (
            <div className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              {error}
            </div>
          )}
          {notEnough ? (
            <p className="text-sm text-muted-foreground">
              Ingest at least 2 documents to get a library overview.
            </p>
          ) : isStreaming && !currentSummary ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 size={14} className="animate-spin" />
              Summarizing...
            </div>
          ) : currentSummary ? (
            <div className="space-y-2">
              <pre className="whitespace-pre-wrap font-sans text-sm text-foreground leading-relaxed">
                {currentSummary}
                {isStreaming && <span className="animate-pulse">▍</span>}
              </pre>
              {!isStreaming && (
                <button
                  onClick={() => void generate(activeMode)}
                  className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
                >
                  <RefreshCw size={12} />
                  Regenerate
                </button>
              )}
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              <p className="text-sm text-muted-foreground">
                Generate a holistic summary across all your documents.
              </p>
              <button
                onClick={() => void generate(activeMode)}
                className="self-start rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
              >
                Generate
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

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
      <h2 className="mb-1 text-lg font-semibold text-foreground">No documents yet</h2>
      <p className="mb-6 text-sm text-muted-foreground">Add your first document to get started.</p>
      <button
        onClick={onAdd}
        className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
      >
        Add your first document
      </button>
    </div>
  )
}

const ALL_CONTENT_TYPES: ContentType[] = ["book", "paper", "conversation", "notes", "code"]

interface SearchPanelProps {
  query: string
  onDocumentClick: (id: string) => void
}

function SearchPanel({ query, onDocumentClick }: SearchPanelProps) {
  const [filterTypes, setFilterTypes] = useState<Set<ContentType>>(new Set())
  const [groups, setGroups] = useState<DocumentGroup[]>([])
  const [loading, setLoading] = useState(false)
  const debouncedQuery = useDebounce(query, 300)

  useEffect(() => {
    if (!debouncedQuery.trim()) {
      setGroups([])
      return
    }
    let cancelled = false
    setLoading(true)
    const ctypes = [...filterTypes].join(",")
    fetchSearch(debouncedQuery, ctypes)
      .then((data) => {
        if (!cancelled) setGroups(data)
      })
      .catch(() => {
        if (!cancelled) setGroups([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [debouncedQuery, filterTypes])

  function toggleType(ct: ContentType) {
    setFilterTypes((prev) => {
      const next = new Set(prev)
      if (next.has(ct)) next.delete(ct)
      else next.add(ct)
      return next
    })
  }

  const totalMatches = groups.reduce((n, g) => n + g.matches.length, 0)

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        {ALL_CONTENT_TYPES.map((ct) => (
          <button
            key={ct}
            onClick={() => toggleType(ct)}
            className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
              filterTypes.has(ct)
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-muted text-muted-foreground hover:bg-accent"
            }`}
          >
            {ct}
          </button>
        ))}
      </div>

      {loading && (
        <p className="py-6 text-center text-sm text-muted-foreground">Searching...</p>
      )}

      {!loading && debouncedQuery && groups.length === 0 && (
        <div className="flex flex-col items-center py-16 text-center">
          <p className="text-sm text-muted-foreground">
            No results for &quot;{debouncedQuery}&quot;
          </p>
        </div>
      )}

      {!loading && groups.length > 0 && (
        <>
          <p className="text-xs text-muted-foreground">
            {totalMatches} match{totalMatches !== 1 ? "es" : ""} across {groups.length}{" "}
            document{groups.length !== 1 ? "s" : ""}
          </p>
          <div className="flex flex-col gap-4">
            {groups.map((group) => (
              <div key={group.document_id} className="rounded-lg border border-border bg-card">
                <button
                  className="flex w-full items-center gap-2 rounded-t-lg p-3 text-left hover:bg-accent/50"
                  onClick={() => onDocumentClick(group.document_id)}
                >
                  <FileText size={15} className="shrink-0 text-primary" />
                  <span className="font-medium text-sm">{group.document_title}</span>
                  <span className="ml-auto rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                    {group.content_type}
                  </span>
                </button>
                <div className="divide-y divide-border border-t border-border">
                  {group.matches.map((match) => (
                    <button
                      key={match.chunk_id}
                      className="flex w-full flex-col gap-1 px-4 py-2 text-left hover:bg-accent/30"
                      onClick={() => onDocumentClick(match.document_id)}
                    >
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <span>{match.section_heading || "Untitled section"}</span>
                        {match.page > 0 && <span>· p.{match.page}</span>}
                        <span className="ml-auto">
                          {(match.relevance_score * 100).toFixed(0)}%
                        </span>
                      </div>
                      <p className="line-clamp-2 text-xs text-foreground/80">{match.text_excerpt}</p>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

export default function Learning() {
  const activeDocumentId = useAppStore((s) => s.activeDocumentId)
  const setActiveDocument = useAppStore((s) => s.setActiveDocument)
  const queryClient = useQueryClient()

  const [searchParams, setSearchParams] = useSearchParams()
  const tagFilter = searchParams.get("tag")

  const [search, setSearch] = useState("")
  const [viewMode, setViewMode] = useState<ViewMode>("grid")
  const [selectedTypes, setSelectedTypes] = useState<Set<ContentType>>(new Set())
  const [sort, setSort] = useState<SortOption>("newest")
  const [page, setPage] = useState(1)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [selectMode, setSelectMode] = useState(false)
  const [bulkConfirm, setBulkConfirm] = useState(false)

  const content_type = selectedTypes.size > 0 ? [...selectedTypes].join(",") : undefined

  const { data: pageData, isLoading } = useQuery({
    queryKey: ["documents", content_type, tagFilter, sort, page, PAGE_SIZE],
    queryFn: () =>
      fetchDocuments({
        content_type,
        tag: tagFilter ?? undefined,
        sort,
        page,
        page_size: PAGE_SIZE,
      }),
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
    setActiveDocument(id)
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

  if (activeDocumentId) {
    return (
      <DocumentReader
        documentId={activeDocumentId}
        onBack={() => setActiveDocument(null)}
      />
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
            <ViewToggle value={viewMode} onChange={setViewMode} />
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

          {isLoading ? (
            <LoadingSkeleton />
          ) : total === 0 && !tagFilter && selectedTypes.size === 0 ? (
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

              {/* Library overview — only on first page, no active filters */}
              {selectedTypes.size === 0 && !tagFilter && page === 1 && !selectMode && (
                <LibraryOverview />
              )}

              {/* Recently accessed — hide when filters active */}
              {recentItems && recentItems.length > 0 && selectedTypes.size === 0 && !tagFilter && page === 1 && (
                <section>
                  <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Recently accessed
                  </h2>
                  {viewMode === "grid" ? (
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
                      {recentItems.map((doc) => (
                        <DocumentCard
                          key={doc.id}
                          doc={doc}
                          onClick={handleDocumentClick}
                          onTagClick={handleTagClick}
                          onTagsChange={handleTagsChange}
                          onDelete={!selectMode ? handleDeleteDocument : undefined}
                          onContentTypeChange={handleContentTypeChange}
                          selected={selectedIds.has(doc.id)}
                          onSelect={selectMode ? handleSelect : undefined}
                        />
                      ))}
                    </div>
                  ) : (
                    <div className="flex flex-col gap-2">
                      {recentItems.map((doc) => (
                        <DocumentRow key={doc.id} doc={doc} onClick={handleDocumentClick} />
                      ))}
                    </div>
                  )}
                </section>
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
                {items.length === 0 ? (
                  <p className="py-8 text-center text-sm text-muted-foreground">
                    {tagFilter
                      ? `No documents tagged "${tagFilter}".`
                      : "No documents match your filters."}
                  </p>
                ) : viewMode === "grid" ? (
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
                        selected={selectedIds.has(doc.id)}
                        onSelect={selectMode ? handleSelect : undefined}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="flex flex-col gap-2">
                    {items.map((doc) => (
                      <DocumentRow key={doc.id} doc={doc} onClick={handleDocumentClick} />
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
