// Full-text search panel with content-type filter chips and grouped
// document hits. Owns its debounced query + filter state internally; the
// parent only provides the raw query string and a click callback.

import { FileText } from "lucide-react"
import { useEffect, useState } from "react"

import { CONTENT_TYPE_ICONS } from "@/components/library/utils"
import type { ContentType } from "@/components/library/types"
import { useDebounce } from "@/hooks/useDebounce"
import { cn } from "@/lib/utils"

import { fetchSearch } from "./api"
import type { DocumentGroup } from "./types"

const ALL_CONTENT_TYPES: ContentType[] = ["book", "paper", "conversation", "notes", "code"]

interface SearchPanelProps {
  query: string
  onDocumentClick: (id: string) => void
}

export function SearchPanel({ query, onDocumentClick }: SearchPanelProps) {
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
        {ALL_CONTENT_TYPES.map((ct) => {
          const Icon = CONTENT_TYPE_ICONS[ct] || FileText
          const isActive = filterTypes.has(ct)
          return (
            <button
              key={ct}
              onClick={() => toggleType(ct)}
              className={cn(
                "flex items-center gap-1.5 rounded-full border px-3 py-1 text-[10px] font-bold uppercase tracking-wider transition-colors",
                isActive
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-muted text-muted-foreground hover:bg-accent"
              )}
            >
              <Icon size={12} />
              {ct.replace(/_/g, " ")}
            </button>
          )
        })}
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
