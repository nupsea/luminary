/**
 * Global Cmd+K / Ctrl+K search dialog (2D.3 + 2D.4).
 *
 * Renders against UnifiedSearchResult only -- the per-endpoint shape
 * (DocumentGroup, NoteSearchItem, FlashcardResponse) never reaches this
 * component. Adapters live in @/lib/unifiedSearch.
 */

import { FileText, Layers, Search, StickyNote, X } from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"

import { useDebounce } from "@/hooks/useDebounce"
import {
  fetchUnifiedSearch,
  loadRecentSeeks,
  pushRecentSeek,
  type SearchKind,
  type UnifiedSearchResult,
} from "@/lib/unifiedSearch"
import { cn } from "@/lib/utils"
import { useAppStore } from "@/store"

interface SearchDialogProps {
  open: boolean
  onClose: () => void
}

const KINDS: { id: SearchKind; label: string; icon: typeof FileText }[] = [
  { id: "document", label: "Documents", icon: FileText },
  { id: "note", label: "Notes", icon: StickyNote },
  { id: "flashcard", label: "Flashcards", icon: Layers },
]

const KIND_ICON: Record<SearchKind, typeof FileText> = {
  document: FileText,
  note: StickyNote,
  flashcard: Layers,
}

export function SearchDialog({ open, onClose }: SearchDialogProps) {
  const [query, setQuery] = useState("")
  const [results, setResults] = useState<UnifiedSearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [activeKinds, setActiveKinds] = useState<Set<SearchKind>>(
    () => new Set<SearchKind>(["document", "note", "flashcard"]),
  )
  const [recent, setRecent] = useState<string[]>([])
  const inputRef = useRef<HTMLInputElement>(null)
  const debouncedQuery = useDebounce(query, 300)
  const setActiveDocument = useAppStore((s) => s.setActiveDocument)
  const setNotesDocumentId = useAppStore((s) => s.setNotesDocumentId)
  const navigate = useNavigate()

  useEffect(() => {
    if (open) {
      setQuery("")
      setResults([])
      setRecent(loadRecentSeeks())
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [open])

  useEffect(() => {
    if (!debouncedQuery.trim()) {
      setResults([])
      return
    }
    let cancelled = false
    setLoading(true)
    fetchUnifiedSearch({
      q: debouncedQuery,
      kinds: Array.from(activeKinds),
    })
      .then((rows) => {
        if (!cancelled) setResults(rows)
      })
      .catch(() => {
        if (!cancelled) setResults([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [debouncedQuery, activeKinds])

  useEffect(() => {
    if (!open) return
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [open, onClose])

  const handleResultClick = useCallback(
    (r: UnifiedSearchResult) => {
      pushRecentSeek(query)
      if (r.kind === "document") {
        if (r.documentId) setActiveDocument(r.documentId)
        navigate("/library")
      } else if (r.kind === "note") {
        if (r.documentId) setNotesDocumentId(r.documentId)
        navigate("/notes")
      } else {
        // Flashcard: route to Study. Use documentId so the study page can
        // restore deck context; falls through to landing when null.
        if (r.documentId) setActiveDocument(r.documentId)
        navigate("/study")
      }
      onClose()
    },
    [navigate, onClose, query, setActiveDocument, setNotesDocumentId],
  )

  const handleRecentClick = useCallback((q: string) => {
    setQuery(q)
    setTimeout(() => inputRef.current?.focus(), 0)
  }, [])

  const toggleKind = useCallback((k: SearchKind) => {
    setActiveKinds((prev) => {
      const next = new Set(prev)
      if (next.has(k)) next.delete(k)
      else next.add(k)
      // Don't allow zero kinds -- empty facet set returns nothing, confusing UX.
      if (next.size === 0) next.add(k)
      return next
    })
  }, [])

  const counts = useMemo(() => {
    const c: Record<SearchKind, number> = { document: 0, note: 0, flashcard: 0 }
    for (const r of results) c[r.kind] += 1
    return c
  }, [results])

  if (!open) return null

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
            placeholder="Search documents, notes, flashcards…"
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

        {/* Facet chips */}
        <div className="flex items-center gap-1.5 border-b border-border px-4 py-2">
          {KINDS.map(({ id, label, icon: Icon }) => {
            const active = activeKinds.has(id)
            return (
              <button
                key={id}
                onClick={() => toggleKind(id)}
                className={cn(
                  "flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs transition-colors",
                  active
                    ? "border-primary bg-primary/15 text-primary"
                    : "border-border bg-background text-muted-foreground hover:text-foreground",
                )}
              >
                <Icon size={11} />
                {label}
                {query && active && counts[id] > 0 && (
                  <span className="text-[10px] opacity-70">{counts[id]}</span>
                )}
              </button>
            )
          })}
        </div>

        {/* Results / recents */}
        <div className="max-h-[60vh] overflow-y-auto">
          {!query && recent.length > 0 && (
            <div className="px-4 py-3">
              <p className="lum-eyebrow mb-1.5">Recent</p>
              <div className="flex flex-col">
                {recent.map((r) => (
                  <button
                    key={r}
                    onClick={() => handleRecentClick(r)}
                    className="flex items-center gap-2 rounded px-2 py-1.5 text-left text-sm text-foreground/80 hover:bg-accent"
                  >
                    <Search size={12} className="shrink-0 text-muted-foreground" />
                    <span className="truncate">{r}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {!query && recent.length === 0 && (
            <p className="px-4 py-6 text-center text-sm text-muted-foreground">
              Start typing to search across documents, notes, and flashcards.
            </p>
          )}

          {loading && (
            <p className="px-4 py-6 text-center text-sm text-muted-foreground">Searching…</p>
          )}
          {!loading && query && results.length === 0 && (
            <p className="px-4 py-6 text-center text-sm text-muted-foreground">
              No results for &quot;{query}&quot;
            </p>
          )}
          {!loading && results.length > 0 && (
            <>
              <p className="px-4 pt-3 text-xs text-muted-foreground">
                {results.length} result{results.length !== 1 ? "s" : ""}
              </p>
              <ul className="flex flex-col">
                {results.map((r) => {
                  const Icon = KIND_ICON[r.kind]
                  return (
                    <li key={r.key}>
                      <button
                        onClick={() => handleResultClick(r)}
                        className="flex w-full flex-col gap-0.5 border-b border-border px-4 py-2 text-left transition-colors last:border-0 hover:bg-accent"
                      >
                        <div className="flex items-center gap-2 text-sm text-foreground">
                          <Icon size={13} className="shrink-0 text-primary" />
                          <span className="truncate font-medium">{r.title}</span>
                          <span className="ml-auto shrink-0 text-[10px] uppercase tracking-wide text-muted-foreground">
                            {r.kind}
                          </span>
                        </div>
                        {(r.snippet || r.context) && (
                          <div className="flex items-center gap-2 pl-5 text-xs text-muted-foreground">
                            {r.context && <span className="shrink-0">{r.context}</span>}
                            {r.snippet && (
                              <span className="line-clamp-1 text-foreground/70">{r.snippet}</span>
                            )}
                          </div>
                        )}
                      </button>
                    </li>
                  )
                })}
              </ul>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
