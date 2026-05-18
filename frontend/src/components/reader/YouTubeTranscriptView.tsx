import { useQuery } from "@tanstack/react-query"
import { ExternalLink, Loader2, Search, X } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { apiGet } from "@/lib/apiClient"
import type { ChunkItem, DocumentDetail } from "./types"
import { relativeDate } from "@/components/library/utils"

const fetchChunks = (documentId: string): Promise<ChunkItem[]> =>
  apiGet<ChunkItem[]>(`/documents/${documentId}/chunks`)

function formatDuration(seconds: number | null): string | null {
  if (seconds == null) return null
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
  return `${m}:${String(s).padStart(2, "0")}`
}

function formatStartTime(seconds: number | null): string | null {
  if (seconds == null) return null
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
  return `${m}:${String(s).padStart(2, "0")}`
}

/** Highlight all occurrences of `term` in `text` with <mark> wrapper. */
function highlightText(text: string, term: string): React.ReactNode {
  if (!term.trim()) return text
  const lower = text.toLowerCase()
  const lowerTerm = term.toLowerCase()
  const parts: React.ReactNode[] = []
  let cursor = 0
  let idx = lower.indexOf(lowerTerm, cursor)
  while (idx >= 0) {
    if (idx > cursor) parts.push(text.slice(cursor, idx))
    parts.push(
      <mark key={idx} className="bg-yellow-200/80 dark:bg-yellow-500/40 rounded-sm px-0.5">
        {text.slice(idx, idx + term.length)}
      </mark>
    )
    cursor = idx + term.length
    idx = lower.indexOf(lowerTerm, cursor)
  }
  if (cursor < text.length) parts.push(text.slice(cursor))
  return <>{parts}</>
}

interface YouTubeTranscriptViewProps {
  doc: DocumentDetail
  initialSectionId?: string | null
  initialChunkId?: string | null
}

export function YouTubeTranscriptView({ doc, initialSectionId, initialChunkId }: YouTubeTranscriptViewProps) {
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState("")
  const searchInputRef = useRef<HTMLInputElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)

  const { data: chunks, isLoading, error } = useQuery({
    queryKey: ["document-chunks", doc.id],
    queryFn: () => fetchChunks(doc.id),
    // Poll every 10 seconds so processing videos refresh automatically
    refetchInterval: (query) => {
      const data = query.state.data
      if (!data || data.length === 0) return 10_000
      return false
    },
  })

  // Scroll to initialSectionId or initialChunkId once chunks load
  useEffect(() => {
    if (!chunks || chunks.length === 0 || !contentRef.current) return

    // Prioritize chunk_id if provided (exact match)
    if (initialChunkId) {
      const el = document.getElementById(`chunk-${initialChunkId}`)
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "start" })
        return
      }
    }

    // Fallback to section_id
    if (initialSectionId) {
      const el = contentRef.current.querySelector(`[data-section-id="${initialSectionId}"]`)
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "start" })
      }
    }
  }, [initialSectionId, initialChunkId, chunks])

  // Cmd+F / Ctrl+F opens search bar
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "f") {
        e.preventDefault()
        setSearchOpen(true)
      }
      if (e.key === "Escape" && searchOpen) {
        setSearchOpen(false)
        setSearchQuery("")
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [searchOpen])

  // Focus search input when opened
  useEffect(() => {
    if (searchOpen) {
      searchInputRef.current?.focus()
    }
  }, [searchOpen])

  // Scroll first matching chunk into view
  useEffect(() => {
    if (!searchQuery.trim() || !contentRef.current) return
    const firstMark = contentRef.current.querySelector("mark")
    if (firstMark) {
      firstMark.scrollIntoView({ behavior: "smooth", block: "nearest" })
    }
  }, [searchQuery])

  const closeSearch = useCallback(() => {
    setSearchOpen(false)
    setSearchQuery("")
  }, [])

  const duration = formatDuration(doc.audio_duration_seconds ?? null)
  const videoUrl = doc.youtube_url ?? doc.source_url

  const matchingChunkIds = searchQuery.trim()
    ? new Set(
        (chunks ?? [])
          .filter((c) => c.text.toLowerCase().includes(searchQuery.toLowerCase()))
          .map((c) => c.id)
      )
    : null

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Video metadata header */}
      <div className="px-6 py-4 border-b border-border bg-muted/30 shrink-0">
        <h2 className="text-base font-semibold text-foreground mb-1">
          {doc.video_title ?? doc.title}
        </h2>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {doc.channel_name && (
            <span>{doc.channel_name}</span>
          )}
          {videoUrl && (
            <a
              href={videoUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-primary hover:underline"
            >
              Watch on YouTube
              <ExternalLink size={11} />
            </a>
          )}
          {duration && <span>{duration}</span>}
          <span>Ingested {relativeDate(doc.created_at)}</span>
        </div>
      </div>

      {/* Keyword search bar */}
      {searchOpen && (
        <div className="px-4 py-2 border-b border-border bg-background shrink-0 flex items-center gap-2">
          <Search size={14} className="text-muted-foreground shrink-0" />
          <input
            ref={searchInputRef}
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search transcript..."
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
          {searchQuery && (
            <span className="text-xs text-muted-foreground">
              {matchingChunkIds?.size ?? 0} match{matchingChunkIds?.size !== 1 ? "es" : ""}
            </span>
          )}
          <button
            onClick={closeSearch}
            className="text-muted-foreground hover:text-foreground"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* Transcript content */}
      <div ref={contentRef} className="flex-1 overflow-auto px-8 py-6">
        <div className="max-w-3xl mx-auto">
          {isLoading && (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          )}

          {error && (
            <p className="text-sm text-destructive">
              Failed to load transcript.
            </p>
          )}

          {!isLoading && !error && chunks && chunks.length === 0 && (
            <div className="flex flex-col items-center gap-3 py-12">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              <p className="text-sm text-muted-foreground">
                Transcript is being processed. Check back shortly.
              </p>
            </div>
          )}

          {chunks && chunks.length > 0 && (
            <div className="space-y-4">
              {chunks
                .filter((c) => !matchingChunkIds || matchingChunkIds.has(c.id))
                .map((chunk) => (
                  <div
                    key={chunk.id}
                    id={`chunk-${chunk.id}`}
                    data-section-id={chunk.section_id || ""}
                    className="text-sm leading-relaxed text-foreground"
                  >
                    {chunk.start_time != null && (
                      <span className="mr-2 font-mono text-xs text-muted-foreground">
                        [{formatStartTime(chunk.start_time)}]
                      </span>
                    )}
                    {chunk.speaker && (
                      <span className="font-medium text-muted-foreground mr-2">
                        [{chunk.speaker}]
                      </span>
                    )}
                    {highlightText(chunk.text, searchQuery)}
                  </div>
                ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
