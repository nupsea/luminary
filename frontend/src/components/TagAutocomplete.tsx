/**
 * TagAutocomplete -- debounced tag input with hierarchy-aware autocomplete.
 *
 * Replaces the flat text input in NoteEditorDialog for tag entry.
 * Features:
 *   - Debounced (200ms) GET /tags/autocomplete?q= on keystroke
 *   - Dropdown: each result shows full slug as primary text and parent as muted secondary
 *   - Typing 'root/' fires autocomplete?q=root/ to show children only
 *   - Arrow-key up/down navigation; Enter selects; Escape closes
 *   - Chip display (X to remove) preserved -- same look as before
 *   - Comma or Enter when no dropdown item focused commits the typed text as a tag
 */

import { useEffect, useRef, useState } from "react"
import { Tag, X } from "lucide-react"
import { useDebounce } from "@/hooks/useDebounce"
import { API_BASE } from "@/lib/config"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AutocompleteResult {
  id: string
  display_name: string
  parent_tag: string | null
  note_count: number
}

// ---------------------------------------------------------------------------
// API helper
// ---------------------------------------------------------------------------

async function fetchAutocomplete(q: string, signal?: AbortSignal): Promise<AutocompleteResult[]> {
  const res = await fetch(`${API_BASE}/tags/autocomplete?q=${encodeURIComponent(q)}`, { signal })
  if (!res.ok) return []
  return res.json() as Promise<AutocompleteResult[]>
}

// ---------------------------------------------------------------------------
// TagBreadcrumb -- renders 'root/child' as breadcrumb style in inline display
// ---------------------------------------------------------------------------

export function TagBreadcrumb({ tag }: { tag: string }) {
  const parts = tag.split("/")
  if (parts.length === 1) {
    return <span className="text-primary">{tag}</span>
  }
  const root = parts[0]
  const rest = "/" + parts.slice(1).join("/")
  return (
    <>
      <span className="text-primary">{root}</span>
      <span className="text-muted-foreground">{rest}</span>
    </>
  )
}

// ---------------------------------------------------------------------------
// TagAutocomplete
// ---------------------------------------------------------------------------

interface TagAutocompleteProps {
  tags: string[]
  onChange: (tags: string[]) => void
  onUnsavedChange?: () => void
}

export function TagAutocomplete({ tags, onChange, onUnsavedChange }: TagAutocompleteProps) {
  const [inputValue, setInputValue] = useState("")
  const [results, setResults] = useState<AutocompleteResult[]>([])
  const [showDropdown, setShowDropdown] = useState(false)
  const [selectedIndex, setSelectedIndex] = useState(-1)
  const debouncedInput = useDebounce(inputValue, 200)
  const abortRef = useRef<AbortController | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Fetch autocomplete results when debounced input changes
  useEffect(() => {
    if (!debouncedInput) {
      setResults([])
      setShowDropdown(false)
      return
    }
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    void fetchAutocomplete(debouncedInput, controller.signal).then((data) => {
      if (controller.signal.aborted) return
      setResults(data)
      setShowDropdown(data.length > 0)
      setSelectedIndex(-1)
    })
    return () => controller.abort()
  }, [debouncedInput])

  function addTag(slug: string) {
    const trimmed = slug.trim()
    if (!trimmed || tags.includes(trimmed)) return
    onChange([...tags, trimmed])
    onUnsavedChange?.()
    setInputValue("")
    setResults([])
    setShowDropdown(false)
    setSelectedIndex(-1)
  }

  function removeTag(tag: string) {
    onChange(tags.filter((t) => t !== tag))
    onUnsavedChange?.()
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault()
      setSelectedIndex((prev) => Math.min(prev + 1, results.length - 1))
    } else if (e.key === "ArrowUp") {
      e.preventDefault()
      setSelectedIndex((prev) => Math.max(prev - 1, -1))
    } else if (e.key === "Enter" || e.key === ",") {
      e.preventDefault()
      if (selectedIndex >= 0 && results[selectedIndex]) {
        addTag(results[selectedIndex].id)
      } else if (inputValue.trim()) {
        addTag(inputValue.trim().replace(/,+$/, ""))
      }
    } else if (e.key === "Escape") {
      setShowDropdown(false)
      setSelectedIndex(-1)
    } else if (e.key === "Backspace" && !inputValue && tags.length > 0) {
      removeTag(tags[tags.length - 1])
    }
  }

  return (
    <div className="relative">
      {/* Chips */}
      {tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-1.5">
          {tags.map((t) => (
            <span
              key={t}
              className="flex items-center gap-0.5 rounded-full bg-muted px-2 py-0.5 text-xs"
            >
              <Tag size={9} className="text-muted-foreground" />
              <TagBreadcrumb tag={t} />
              <button
                type="button"
                onClick={() => removeTag(t)}
                className="ml-0.5 hover:text-foreground text-muted-foreground"
                aria-label={`Remove tag ${t}`}
              >
                <X size={9} />
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Input */}
      <input
        ref={inputRef}
        type="text"
        value={inputValue}
        onChange={(e) => setInputValue(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={() => {
          // Delay to allow click on dropdown item
          setTimeout(() => {
            setShowDropdown(false)
            setSelectedIndex(-1)
          }, 150)
        }}
        onFocus={() => {
          if (results.length > 0) setShowDropdown(true)
        }}
        placeholder="Add tag..."
        className="w-full bg-transparent text-xs text-foreground placeholder:text-muted-foreground focus:outline-none"
      />

      {/* Dropdown */}
      {showDropdown && results.length > 0 && (
        <div className="absolute z-20 mt-1 w-full max-h-40 overflow-y-auto rounded border border-border bg-popover shadow-md">
          {results.map((result, idx) => (
            <button
              key={result.id}
              type="button"
              onMouseDown={(e) => {
                e.preventDefault() // prevent blur before click
                addTag(result.id)
              }}
              className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs ${
                idx === selectedIndex ? "bg-accent" : "hover:bg-accent/60"
              }`}
            >
              <span className="flex-1 font-medium text-foreground">{result.id}</span>
              {result.parent_tag && (
                <span className="text-muted-foreground shrink-0">{result.parent_tag}</span>
              )}
              <span className="text-muted-foreground shrink-0">{result.note_count}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
