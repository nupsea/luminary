/**
 * Global Cmd+K / Ctrl+K search dialog (2D.3 + 2D.4).
 *
 * Renders against UnifiedSearchResult only -- the per-endpoint shape
 * (DocumentGroup, NoteSearchItem, FlashcardResponse) never reaches this
 * component. Adapters live in @/lib/unifiedSearch.
 */

import { FileText, Layers, Loader2, MessageCircle, Search, StickyNote, X } from "lucide-react"
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
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { cn } from "@/lib/utils"
import { useAppStore } from "@/store"
import { API_BASE } from "@/lib/config"

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
  const [dialogMode, setDialogMode] = useState<"search" | "ask">("search")
  const [query, setQuery] = useState("")
  const [results, setResults] = useState<UnifiedSearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [activeKinds, setActiveKinds] = useState<Set<SearchKind>>(
    () => new Set<SearchKind>(["document", "note", "flashcard"]),
  )
  const [recent, setRecent] = useState<string[]>([])
  const inputRef = useRef<HTMLInputElement>(null)
  const askInputRef = useRef<HTMLTextAreaElement>(null)
  const debouncedQuery = useDebounce(query, 300)
  const setActiveDocument = useAppStore((s) => s.setActiveDocument)
  const setNotesDocumentId = useAppStore((s) => s.setNotesDocumentId)
  const navigate = useNavigate()

  // Ask panel state
  const [askQuestion, setAskQuestion] = useState("")
  const [socraticMode, setSocraticMode] = useState(true)
  const [askAnswer, setAskAnswer] = useState("")
  const [askStreaming, setAskStreaming] = useState(false)
  const [askCitations, setAskCitations] = useState<{ section_heading: string; excerpt: string }[]>([])
  const activeDocumentId = useAppStore((s) => s.activeDocumentId)

  useEffect(() => {
    if (open) {
      setQuery("")
      setResults([])
      setAskAnswer("")
      setAskQuestion("")
      setAskCitations([])
      setAskStreaming(false)
      setRecent(loadRecentSeeks())
      setTimeout(() => {
        if (dialogMode === "ask") askInputRef.current?.focus()
        else inputRef.current?.focus()
      }, 50)
    }
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleAskSubmit = useCallback(async () => {
    if (!askQuestion.trim() || askStreaming) return
    setAskAnswer("")
    setAskCitations([])
    setAskStreaming(true)
    try {
      const res = await fetch(`${API_BASE}/qa`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: askQuestion,
          document_ids: activeDocumentId ? [activeDocumentId] : null,
          scope: activeDocumentId ? "single" : "all",
          socratic: socraticMode,
        }),
      })
      if (!res.ok || !res.body) throw new Error("QA failed")
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = ""
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split("\n")
        buf = lines.pop() ?? ""
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue
          try {
            const payload = JSON.parse(line.slice(6)) as Record<string, unknown>
            if (typeof payload.token === "string") {
              setAskAnswer((prev) => prev + payload.token)
            } else if (payload.done) {
              const cites = (payload.citations as { section_heading?: string; excerpt?: string }[] | undefined) ?? []
              setAskCitations(cites.map((c) => ({ section_heading: c.section_heading ?? "", excerpt: c.excerpt ?? "" })))
            }
          } catch { /* malformed line, skip */ }
        }
      }
    } finally {
      setAskStreaming(false)
    }
  }, [askQuestion, askStreaming, activeDocumentId, socraticMode])

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
        {/* Mode tabs */}
        <div className="flex items-center gap-0 border-b border-border px-4 pt-3 pb-0">
          {(["search", "ask"] as const).map((m) => (
            <button
              key={m}
              onClick={() => {
                setDialogMode(m)
                setTimeout(() => {
                  if (m === "ask") askInputRef.current?.focus()
                  else inputRef.current?.focus()
                }, 50)
              }}
              className={cn(
                "flex items-center gap-1.5 border-b-2 px-3 pb-2 text-sm font-medium transition-colors",
                dialogMode === m
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {m === "search" ? <Search size={13} /> : <MessageCircle size={13} />}
              {m === "search" ? "Search" : "Ask"}
            </button>
          ))}
          <div className="ml-auto pb-2">
            <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
              esc
            </kbd>
          </div>
        </div>

        {dialogMode === "ask" ? (
          /* Ask panel */
          <div className="flex flex-col gap-0">
            <div className="flex items-start gap-2 border-b border-border px-4 py-3">
              <MessageCircle size={16} className="mt-0.5 shrink-0 text-muted-foreground" />
              <textarea
                ref={askInputRef}
                value={askQuestion}
                onChange={(e) => setAskQuestion(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault()
                    void handleAskSubmit()
                  }
                }}
                placeholder="Ask a question about your documents…"
                rows={2}
                className="flex-1 resize-none bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
              />
              {askStreaming ? (
                <Loader2 size={14} className="mt-0.5 shrink-0 animate-spin text-muted-foreground" />
              ) : (
                <button
                  onClick={() => void handleAskSubmit()}
                  disabled={!askQuestion.trim()}
                  className="mt-0.5 shrink-0 rounded bg-primary px-2 py-1 text-xs font-medium text-primary-foreground disabled:opacity-40 hover:bg-primary/90"
                >
                  Ask
                </button>
              )}
            </div>
            {/* Socratic toggle */}
            <div className="flex items-center gap-2 border-b border-border px-4 py-2">
              <button
                onClick={() => setSocraticMode((v) => !v)}
                className={cn(
                  "flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs transition-colors",
                  socraticMode
                    ? "border-violet-500/50 bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-400"
                    : "border-border bg-background text-muted-foreground hover:text-foreground",
                )}
              >
                Socratic {socraticMode ? "on" : "off"}
              </button>
              <span className="text-xs text-muted-foreground">
                {socraticMode ? "LLM asks first" : "Direct answer"}
              </span>
              {activeDocumentId && (
                <span className="ml-auto text-xs text-muted-foreground">
                  scope: current doc
                </span>
              )}
            </div>
            {/* Streaming answer */}
            {(askAnswer || askStreaming) && (
              <div className="max-h-[50vh] overflow-y-auto px-4 py-3">
                <MarkdownRenderer>{askAnswer}</MarkdownRenderer>
                {askCitations.length > 0 && (
                  <div className="mt-3 flex flex-col gap-1">
                    {askCitations.slice(0, 3).map((c, i) => (
                      <div key={i} className="rounded bg-muted/50 px-2 py-1 text-xs text-muted-foreground">
                        <span className="font-medium">{c.section_heading}</span>
                        {c.excerpt && <span className="ml-1 opacity-70">— {c.excerpt.slice(0, 80)}…</span>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        ) : (
          <>
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
          </>
        )}
      </div>
    </div>
  )
}
