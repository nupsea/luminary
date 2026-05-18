import { ChevronDown, ChevronUp, Loader2, Search, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { useDebounce } from "@/hooks/useDebounce"
import { apiGet } from "@/lib/apiClient"

export interface DocumentSectionSearchResult {
  section_id: string
  section_heading: string
  match_count: number
  snippet: string
}

interface InDocSearchBarProps {
  documentId: string
  onResults: (results: DocumentSectionSearchResult[]) => void
  onClose: () => void
  hitIndex: number
  totalHits: number
  onPrev: () => void
  onNext: () => void
}

export function InDocSearchBar({
  documentId,
  onResults,
  onClose,
  hitIndex,
  totalHits,
  onPrev,
  onNext,
}: InDocSearchBarProps) {
  const [inputValue, setInputValue] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const debouncedQuery = useDebounce(inputValue, 300)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  useEffect(() => {
    if (!debouncedQuery.trim()) {
      onResults([])
      setError(null)
      return
    }
    setLoading(true)
    setError(null)
    void (async () => {
      try {
        const data = await apiGet<DocumentSectionSearchResult[]>(
          `/documents/${encodeURIComponent(documentId)}/search`,
          { q: debouncedQuery },
        )
        onResults(data)
      } catch {
        setError("Search failed")
        onResults([])
      } finally {
        setLoading(false)
      }
    })()
  }, [debouncedQuery, documentId, onResults])

  return (
    <div className="mb-3 flex flex-col gap-1">
      <div className="flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1">
        {loading ? (
          <Loader2 size={12} className="shrink-0 animate-spin text-muted-foreground" />
        ) : (
          <Search size={12} className="shrink-0 text-muted-foreground" />
        )}
        <input
          ref={inputRef}
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          placeholder="Search in document..."
          className="flex-1 bg-transparent text-xs text-foreground placeholder:text-muted-foreground focus:outline-none"
        />
        {totalHits > 0 && (
          <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
            {hitIndex + 1} of {totalHits}
          </span>
        )}
        {totalHits > 0 && (
          <>
            <button
              onClick={onPrev}
              title="Previous match"
              className="shrink-0 text-muted-foreground hover:text-foreground"
              aria-label="Previous match"
            >
              <ChevronUp size={12} />
            </button>
            <button
              onClick={onNext}
              title="Next match"
              className="shrink-0 text-muted-foreground hover:text-foreground"
              aria-label="Next match"
            >
              <ChevronDown size={12} />
            </button>
          </>
        )}
        <button
          onClick={onClose}
          title="Close search"
          className="shrink-0 text-muted-foreground hover:text-foreground"
          aria-label="Close search"
        >
          <X size={12} />
        </button>
      </div>
      {error && (
        <p className="text-xs text-destructive">{error}</p>
      )}
      {!loading && !error && debouncedQuery.trim() && totalHits === 0 && (
        <p className="text-xs text-muted-foreground">No matches in this document</p>
      )}
    </div>
  )
}
