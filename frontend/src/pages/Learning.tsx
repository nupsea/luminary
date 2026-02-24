import { useQuery } from "@tanstack/react-query"
import { BookPlus, FileText, Plus } from "lucide-react"
import { useEffect, useState } from "react"
import { FilterBar } from "@/components/library/FilterBar"
import { SearchBar } from "@/components/library/SearchBar"
import { SortSelect } from "@/components/library/SortSelect"
import { UploadDialog } from "@/components/library/UploadDialog"
import { ViewToggle } from "@/components/library/ViewToggle"
import { DocumentCard } from "@/components/library/DocumentCard"
import { DocumentRow } from "@/components/library/DocumentRow"
import type { ContentType, DocumentListItem, SortOption, ViewMode } from "@/components/library/types"
import { DocumentReader } from "@/components/reader/DocumentReader"
import { useDebounce } from "@/hooks/useDebounce"
import { useAppStore } from "@/store"

const API_BASE = "http://localhost:8000"

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

async function fetchDocuments(): Promise<DocumentListItem[]> {
  const res = await fetch(`${API_BASE}/documents`)
  if (!res.ok) throw new Error("Failed to fetch documents")
  return res.json() as Promise<DocumentListItem[]>
}

const LEARNING_STATUS_ORDER: Record<string, number> = {
  studied: 3,
  flashcards_generated: 2,
  summarized: 1,
  not_started: 0,
}

function applyFiltersAndSort(
  docs: DocumentListItem[],
  types: Set<ContentType>,
  sort: SortOption,
): DocumentListItem[] {
  let result = docs

  if (types.size > 0) {
    result = result.filter((d) => types.has(d.content_type))
  }

  result = [...result].sort((a, b) => {
    switch (sort) {
      case "newest":
        return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      case "oldest":
        return new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
      case "alphabetical":
        return a.title.localeCompare(b.title)
      case "most-studied":
        return (
          (LEARNING_STATUS_ORDER[b.learning_status] ?? 0) -
          (LEARNING_STATUS_ORDER[a.learning_status] ?? 0)
        )
    }
  })

  return result
}

function LoadingSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <div
          key={i}
          className="h-28 animate-pulse rounded-lg border border-border bg-muted"
        />
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
  const [search, setSearch] = useState("")
  const [viewMode, setViewMode] = useState<ViewMode>("grid")
  const [selectedTypes, setSelectedTypes] = useState<Set<ContentType>>(new Set())
  const [sort, setSort] = useState<SortOption>("newest")
  const [uploadOpen, setUploadOpen] = useState(false)

  const { data: documents, isLoading } = useQuery({
    queryKey: ["documents"],
    queryFn: fetchDocuments,
  })

  function handleDocumentClick(id: string) {
    setActiveDocument(id)
  }

  if (activeDocumentId) {
    return (
      <DocumentReader
        documentId={activeDocumentId}
        onBack={() => setActiveDocument(null)}
      />
    )
  }

  const allDocs = documents ?? []
  const filtered = applyFiltersAndSort(allDocs, selectedTypes, sort)

  const recentlyAccessed = [...allDocs]
    .sort(
      (a, b) =>
        new Date(b.last_accessed_at).getTime() - new Date(a.last_accessed_at).getTime(),
    )
    .slice(0, 5)

  const searchActive = search.trim().length > 0

  return (
    <div className="flex h-full flex-col gap-4 p-6">
      <div className="flex flex-wrap items-center gap-3">
        <SearchBar value={search} onChange={setSearch} />
        {!searchActive && (
          <>
            <SortSelect value={sort} onChange={setSort} />
            <ViewToggle value={viewMode} onChange={setViewMode} />
          </>
        )}
        <button
          onClick={() => setUploadOpen(true)}
          className="flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          <Plus size={14} />
          Add Content
        </button>
      </div>

      {searchActive ? (
        <SearchPanel query={search} onDocumentClick={handleDocumentClick} />
      ) : (
        <>
          <FilterBar selected={selectedTypes} onChange={setSelectedTypes} />

          {isLoading ? (
            <LoadingSkeleton />
          ) : allDocs.length === 0 ? (
            <EmptyState onAdd={() => setUploadOpen(true)} />
          ) : (
            <>
              {recentlyAccessed.length > 0 && selectedTypes.size === 0 && (
                <section>
                  <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Recently accessed
                  </h2>
                  {viewMode === "grid" ? (
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
                      {recentlyAccessed.map((doc) => (
                        <DocumentCard key={doc.id} doc={doc} onClick={handleDocumentClick} />
                      ))}
                    </div>
                  ) : (
                    <div className="flex flex-col gap-2">
                      {recentlyAccessed.map((doc) => (
                        <DocumentRow key={doc.id} doc={doc} onClick={handleDocumentClick} />
                      ))}
                    </div>
                  )}
                </section>
              )}

              <section>
                <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {selectedTypes.size > 0 ? "Results" : "All documents"}
                </h2>
                {filtered.length === 0 ? (
                  <p className="py-8 text-center text-sm text-muted-foreground">
                    No documents match your filters.
                  </p>
                ) : viewMode === "grid" ? (
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                    {filtered.map((doc) => (
                      <DocumentCard key={doc.id} doc={doc} onClick={handleDocumentClick} />
                    ))}
                  </div>
                ) : (
                  <div className="flex flex-col gap-2">
                    {filtered.map((doc) => (
                      <DocumentRow key={doc.id} doc={doc} onClick={handleDocumentClick} />
                    ))}
                  </div>
                )}
              </section>
            </>
          )}
        </>
      )}

      <UploadDialog open={uploadOpen} onClose={() => setUploadOpen(false)} />
    </div>
  )
}
