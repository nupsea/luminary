/**
 * Global Cmd+K / Ctrl+K search dialog.
 *
 * Opens a full-screen overlay with a search input that queries GET /search
 * with 300 ms debounce. Results are grouped by document. Clicking a result
 * closes the dialog and navigates the user to the document in Learning tab.
 */

import { FileText, Search, X } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useDebounce } from "@/hooks/useDebounce"
import { useAppStore } from "@/store"

import { apiGet } from "@/lib/apiClient"

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

interface SearchResponse {
  results: DocumentGroup[]
}

const fetchSearch = (q: string): Promise<SearchResponse> =>
  apiGet<SearchResponse>("/search", { q, limit: 20 })

interface SearchDialogProps {
  open: boolean
  onClose: () => void
}

export function SearchDialog({ open, onClose }: SearchDialogProps) {
  const [query, setQuery] = useState("")
  const [groups, setGroups] = useState<DocumentGroup[]>([])
  const [loading, setLoading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const debouncedQuery = useDebounce(query, 300)
  const setActiveDocument = useAppStore((s) => s.setActiveDocument)
  const navigate = useNavigate()

  // Focus input when opened
  useEffect(() => {
    if (open) {
      setQuery("")
      setGroups([])
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [open])

  // Search on debounced query change
  useEffect(() => {
    if (!debouncedQuery.trim()) {
      setGroups([])
      return
    }
    let cancelled = false
    setLoading(true)
    fetchSearch(debouncedQuery)
      .then((data) => {
        if (!cancelled) setGroups(data.results)
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
  }, [debouncedQuery])

  // Close on Escape
  useEffect(() => {
    if (!open) return
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [open, onClose])

  const handleResultClick = useCallback(
    (documentId: string) => {
      setActiveDocument(documentId)
      navigate("/")
      onClose()
    },
    [setActiveDocument, navigate, onClose],
  )

  if (!open) return null

  const totalMatches = groups.reduce((n, g) => n + g.matches.length, 0)

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 pt-[10vh]"
      onClick={onClose}
    >
      <div
        className="relative flex w-full max-w-xl flex-col overflow-hidden rounded-xl border border-border bg-background shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search input row */}
        <div className="flex items-center gap-2 border-b border-border px-4 py-3">
          <Search size={16} className="shrink-0 text-muted-foreground" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search across all documents..."
            className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
          />
          {query && (
            <button onClick={() => setQuery("")} className="text-muted-foreground hover:text-foreground">
              <X size={14} />
            </button>
          )}
          <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
            esc
          </kbd>
        </div>

        {/* Results */}
        <div className="max-h-[60vh] overflow-y-auto">
          {loading && (
            <p className="px-4 py-6 text-center text-sm text-muted-foreground">Searching...</p>
          )}
          {!loading && query && groups.length === 0 && (
            <p className="px-4 py-6 text-center text-sm text-muted-foreground">
              No results for &quot;{query}&quot;
            </p>
          )}
          {!loading && groups.length > 0 && (
            <>
              <p className="px-4 pt-3 text-xs text-muted-foreground">
                {totalMatches} match{totalMatches !== 1 ? "es" : ""} across {groups.length} document
                {groups.length !== 1 ? "s" : ""}
              </p>
              {groups.map((group) => (
                <div key={group.document_id} className="border-b border-border last:border-0">
                  {/* Document header */}
                  <button
                    className="flex w-full items-center gap-2 px-4 py-2 text-left hover:bg-accent"
                    onClick={() => handleResultClick(group.document_id)}
                  >
                    <FileText size={14} className="shrink-0 text-primary" />
                    <span className="font-medium text-sm text-foreground">{group.document_title}</span>
                    <span className="ml-auto text-xs text-muted-foreground">{group.content_type}</span>
                  </button>
                  {/* Match rows */}
                  {group.matches.map((match) => (
                    <button
                      key={match.chunk_id}
                      className="flex w-full flex-col gap-0.5 px-8 py-2 text-left hover:bg-accent/60"
                      onClick={() => handleResultClick(match.document_id)}
                    >
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <span>{match.section_heading || "Untitled section"}</span>
                        {match.page > 0 && <span>· p.{match.page}</span>}
                      </div>
                      <p className="line-clamp-2 text-xs text-foreground/80">{match.text_excerpt}</p>
                    </button>
                  ))}
                </div>
              ))}
            </>
          )}
          {!query && (
            <p className="px-4 py-6 text-center text-sm text-muted-foreground">
              Start typing to search across all documents.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
