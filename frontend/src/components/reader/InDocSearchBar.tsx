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
  /** Prefill the input the first time the bar opens (e.g., from a tag click). */
  initialQuery?: string
  /** Fires once after initialQuery has been pushed into the input, so the
   * caller can clear its pending state and not re-prefill on next open. */
  onConsumeInitialQuery?: () => void
  /** The settled query, so the reader can mark the term in the body it shows.
   * Fires with the debounced value, matching what was actually searched for. */
  onQueryChange?: (query: string) => void
}

export function InDocSearchBar({
  documentId,
  onResults,
  onClose,
  hitIndex,
  totalHits,
  onPrev,
  onNext,
  initialQuery,
  onConsumeInitialQuery,
  onQueryChange,
}: InDocSearchBarProps) {
  const [inputValue, setInputValue] = useState(initialQuery ?? "")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const debouncedQuery = useDebounce(inputValue, 300)

  useEffect(() => {
    inputRef.current?.focus()
    if (initialQuery) {
      // Select the prefilled query so the user can immediately type to replace.
      inputRef.current?.select()
      onConsumeInitialQuery?.()
    }
    // Run once on mount only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // The callbacks arrive as inline arrows, so their identity changes on every
  // render of the reader. Held in refs and kept out of the dep arrays below,
  // because naming them as dependencies made the search feed itself: a result
  // set -> a reader re-render -> fresh callback identity -> the same query
  // refetched, forever. The visible symptom was Next/Prev doing nothing, since
  // the reader resets the hit index to 0 every time results arrive.
  const onResultsRef = useRef(onResults)
  const onQueryChangeRef = useRef(onQueryChange)
  useEffect(() => {
    onResultsRef.current = onResults
    onQueryChangeRef.current = onQueryChange
  })

  useEffect(() => {
    onQueryChangeRef.current?.(debouncedQuery.trim())
  }, [debouncedQuery])

  useEffect(() => {
    if (!debouncedQuery.trim()) {
      onResultsRef.current([])
      setError(null)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    void (async () => {
      try {
        const data = await apiGet<DocumentSectionSearchResult[]>(
          `/documents/${encodeURIComponent(documentId)}/search`,
          { q: debouncedQuery },
        )
        // A slower earlier query must not overwrite a newer one's results.
        if (cancelled) return
        onResultsRef.current(data)
      } catch {
        if (cancelled) return
        setError("Search failed")
        onResultsRef.current([])
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [debouncedQuery, documentId])

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
