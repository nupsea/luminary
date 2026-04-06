/**
 * LinkAutocomplete -- debounced popover for inserting [[id|text]] note links.
 *
 * Props:
 *   query         — current search query (from the text after `[[`)
 *   onSelect      — called with (id, preview, linkType) when user confirms a note
 *   onClose       — called when the popover should be dismissed
 *
 * The parent (NoteEditorDialog) is responsible for:
 *   - Detecting `[[` in textarea content and extracting the query string
 *   - Positioning this component near the cursor
 *   - Calling onSelect to insert the [[id|text]] marker
 *
 * S171: includes a 5-option link type segmented control shown before confirmation.
 */

import { useEffect, useRef, useState } from "react"
import { Loader2 } from "lucide-react"
import { API_BASE } from "@/lib/config"

const LINK_TYPES = ["elaborates", "contradicts", "see-also", "supports", "questions"] as const
type LinkType = typeof LINK_TYPES[number]

interface AutocompleteItem {
  id: string
  preview: string
}

interface LinkAutocompleteProps {
  query: string
  onSelect: (id: string, preview: string, linkType: LinkType) => void
  onClose: () => void
}

async function fetchAutocomplete(q: string): Promise<AutocompleteItem[]> {
  try {
    const res = await fetch(
      `${API_BASE}/notes/autocomplete?q=${encodeURIComponent(q)}`
    )
    if (!res.ok) return []
    return res.json() as Promise<AutocompleteItem[]>
  } catch {
    return []
  }
}

export function LinkAutocomplete({ query, onSelect, onClose }: LinkAutocompleteProps) {
  const [results, setResults] = useState<AutocompleteItem[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [activeIdx, setActiveIdx] = useState(0)
  const [linkType, setLinkType] = useState<LinkType>("see-also")
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  // Debounced fetch when query changes
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    setIsLoading(true)
    debounceRef.current = setTimeout(() => {
      void fetchAutocomplete(query).then((items) => {
        setResults(items)
        setActiveIdx(0)
        setIsLoading(false)
      })
    }, 150)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [query])

  // Keyboard navigation
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "ArrowDown") {
        e.preventDefault()
        setActiveIdx((i) => Math.min(i + 1, results.length - 1))
      } else if (e.key === "ArrowUp") {
        e.preventDefault()
        setActiveIdx((i) => Math.max(i - 1, 0))
      } else if (e.key === "Enter") {
        e.preventDefault()
        if (results[activeIdx]) {
          onSelect(results[activeIdx].id, results[activeIdx].preview, linkType)
        }
      } else if (e.key === "Escape") {
        onClose()
      }
    }
    window.addEventListener("keydown", handleKey)
    return () => window.removeEventListener("keydown", handleKey)
  }, [results, activeIdx, linkType, onSelect, onClose])

  // Click outside closes
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    document.addEventListener("mousedown", handleClick)
    return () => document.removeEventListener("mousedown", handleClick)
  }, [onClose])

  return (
    <div
      ref={containerRef}
      className="absolute z-50 min-w-[280px] max-w-[360px] rounded-md border border-border bg-background shadow-lg overflow-hidden"
    >
      {/* Link type segmented control — shown before confirmation */}
      <div className="flex items-center gap-0.5 border-b border-border px-2 py-1.5">
        {LINK_TYPES.map((lt) => (
          <button
            key={lt}
            onMouseDown={(e) => {
              e.preventDefault()
              setLinkType(lt)
            }}
            className={`rounded px-1.5 py-0.5 text-[10px] font-medium transition-colors ${
              linkType === lt
                ? "bg-indigo-600 text-white"
                : "text-muted-foreground hover:bg-accent/50"
            }`}
          >
            {lt}
          </button>
        ))}
      </div>

      {/* Results */}
      {isLoading ? (
        <div className="flex items-center gap-1.5 px-3 py-2 text-xs text-muted-foreground">
          <Loader2 size={12} className="animate-spin" />
          Searching...
        </div>
      ) : results.length === 0 ? (
        <p className="px-3 py-2 text-xs text-muted-foreground">No matching notes</p>
      ) : (
        results.map((item, idx) => (
          <button
            key={item.id}
            onMouseDown={(e) => {
              e.preventDefault() // prevent textarea blur
              onSelect(item.id, item.preview, linkType)
            }}
            className={`block w-full px-3 py-2 text-left text-xs transition-colors ${
              idx === activeIdx
                ? "bg-primary/10 text-foreground"
                : "text-foreground hover:bg-accent/50"
            }`}
          >
            <span className="line-clamp-2 leading-relaxed">{item.preview}</span>
          </button>
        ))
      )}
    </div>
  )
}
