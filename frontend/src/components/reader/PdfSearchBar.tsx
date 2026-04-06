import { useEffect, useRef } from "react"
import { ChevronUp, ChevronDown, X, Search } from "lucide-react"

interface PdfSearchBarProps {
  query: string
  onQueryChange: (q: string) => void
  matchLabel: string
  onNext: () => void
  onPrev: () => void
  onClose: () => void
}

export function PdfSearchBar({
  query,
  onQueryChange,
  matchLabel,
  onNext,
  onPrev,
  onClose,
}: PdfSearchBarProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  return (
    <div className="absolute top-2 right-2 z-50 flex items-center gap-1 bg-background border rounded-lg shadow-lg px-2 py-1.5">
      <Search className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" />
      <input
        ref={inputRef}
        type="text"
        className="w-44 text-sm border-none outline-none bg-transparent px-1"
        placeholder="Find in document..."
        value={query}
        onChange={(e) => onQueryChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            if (e.shiftKey) onPrev()
            else onNext()
          }
          if (e.key === "Escape") onClose()
        }}
        aria-label="Search in PDF"
      />
      {query && (
        <span className="text-xs text-muted-foreground whitespace-nowrap">{matchLabel}</span>
      )}
      <button
        className="p-0.5 rounded hover:bg-accent disabled:opacity-40"
        onClick={onPrev}
        disabled={!query}
        title="Previous match (Shift+Enter)"
        aria-label="Previous match"
      >
        <ChevronUp className="h-4 w-4" />
      </button>
      <button
        className="p-0.5 rounded hover:bg-accent disabled:opacity-40"
        onClick={onNext}
        disabled={!query}
        title="Next match (Enter)"
        aria-label="Next match"
      >
        <ChevronDown className="h-4 w-4" />
      </button>
      <button
        className="p-0.5 rounded hover:bg-accent"
        onClick={onClose}
        title="Close (Escape)"
        aria-label="Close search"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  )
}
