import { useQuery } from "@tanstack/react-query"
import { BookPlus } from "lucide-react"
import { useState } from "react"
import { FilterBar } from "@/components/library/FilterBar"
import { SearchBar } from "@/components/library/SearchBar"
import { SortSelect } from "@/components/library/SortSelect"
import { ViewToggle } from "@/components/library/ViewToggle"
import { DocumentCard } from "@/components/library/DocumentCard"
import { DocumentRow } from "@/components/library/DocumentRow"
import type { ContentType, DocumentListItem, SortOption, ViewMode } from "@/components/library/types"
import { useAppStore } from "@/store"

const API_BASE = "http://localhost:8000"

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
  search: string,
  types: Set<ContentType>,
  sort: SortOption,
): DocumentListItem[] {
  let result = docs

  if (search.trim()) {
    const q = search.toLowerCase()
    result = result.filter((d) => d.title.toLowerCase().includes(q))
  }

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

export default function Learning() {
  const setActiveDocument = useAppStore((s) => s.setActiveDocument)
  const [search, setSearch] = useState("")
  const [viewMode, setViewMode] = useState<ViewMode>("grid")
  const [selectedTypes, setSelectedTypes] = useState<Set<ContentType>>(new Set())
  const [sort, setSort] = useState<SortOption>("newest")

  const { data: documents, isLoading } = useQuery({
    queryKey: ["documents"],
    queryFn: fetchDocuments,
  })

  function handleDocumentClick(id: string) {
    setActiveDocument(id)
  }

  const allDocs = documents ?? []
  const filtered = applyFiltersAndSort(allDocs, search, selectedTypes, sort)

  const recentlyAccessed = [...allDocs]
    .sort(
      (a, b) =>
        new Date(b.last_accessed_at).getTime() - new Date(a.last_accessed_at).getTime(),
    )
    .slice(0, 5)

  return (
    <div className="flex h-full flex-col gap-4 p-6">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3">
        <SearchBar value={search} onChange={setSearch} />
        <SortSelect value={sort} onChange={setSort} />
        <ViewToggle value={viewMode} onChange={setViewMode} />
      </div>

      <FilterBar selected={selectedTypes} onChange={setSelectedTypes} />

      {isLoading ? (
        <LoadingSkeleton />
      ) : allDocs.length === 0 ? (
        <EmptyState onAdd={() => {}} />
      ) : (
        <>
          {/* Recently accessed */}
          {recentlyAccessed.length > 0 && !search && selectedTypes.size === 0 && (
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

          {/* All documents */}
          <section>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {search || selectedTypes.size > 0 ? "Results" : "All documents"}
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
    </div>
  )
}
