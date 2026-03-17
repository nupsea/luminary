/**
 * EPUBViewer — Two-column chapter reader for EPUB documents (S149).
 *
 * Left panel: scrollable chapter TOC with active chapter highlighted.
 * Right panel: sanitized chapter HTML rendered in a Tailwind prose div.
 *
 * SelectionActionBar integration: the parent DocumentReader already wraps
 * its entire left panel in a ref — EPUBViewer is mounted inside that ref,
 * so selection events bubble up automatically without extra wiring here.
 */

import { useQuery } from "@tanstack/react-query"
import { ChevronLeft, ChevronRight, RotateCcw } from "lucide-react"
import { useState } from "react"
import { cn } from "@/lib/utils"
import { Skeleton } from "@/components/ui/skeleton"
import { API_BASE } from "@/lib/config"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface EpubTocItem {
  chapter_index: number
  title: string
  word_count: number
}

interface EpubChapter {
  chapter_index: number
  chapter_title: string
  html: string
  word_count: number
  section_ids: string[]
}

// ---------------------------------------------------------------------------
// API fetch helpers
// ---------------------------------------------------------------------------

async function fetchToc(documentId: string): Promise<EpubTocItem[]> {
  const res = await fetch(`${API_BASE}/documents/${documentId}/epub/toc`)
  if (!res.ok) throw new Error(`Failed to fetch TOC: HTTP ${res.status}`)
  const data = (await res.json()) as { chapters: EpubTocItem[] }
  return data.chapters
}

async function fetchChapter(documentId: string, chapterIndex: number): Promise<EpubChapter> {
  const res = await fetch(`${API_BASE}/documents/${documentId}/epub/chapter/${chapterIndex}`)
  if (!res.ok) throw new Error(`Failed to fetch chapter ${chapterIndex}: HTTP ${res.status}`)
  return res.json() as Promise<EpubChapter>
}

// ---------------------------------------------------------------------------
// EPUBViewer
// ---------------------------------------------------------------------------

interface EPUBViewerProps {
  documentId: string
}

export function EPUBViewer({ documentId }: EPUBViewerProps) {
  const [activeChapter, setActiveChapter] = useState(0)

  // Fetch TOC — long stale time since EPUB structure never changes
  const {
    data: toc,
    isLoading: tocLoading,
    isError: tocError,
    refetch: refetchToc,
  } = useQuery({
    queryKey: ["epub-toc", documentId],
    queryFn: () => fetchToc(documentId),
    staleTime: 300_000,
  })

  // Fetch current chapter
  const {
    data: chapter,
    isLoading: chapterLoading,
    isError: chapterError,
    refetch: refetchChapter,
  } = useQuery({
    queryKey: ["epub-chapter", documentId, activeChapter],
    queryFn: () => fetchChapter(documentId, activeChapter),
    staleTime: 60_000,
    enabled: (toc?.length ?? 0) > 0,
  })

  const totalChapters = toc?.length ?? 0

  function goToPrev() {
    if (activeChapter > 0) setActiveChapter((c) => c - 1)
  }

  function goToNext() {
    if (activeChapter < totalChapters - 1) setActiveChapter((c) => c + 1)
  }

  return (
    <div className="flex h-full overflow-hidden">
      {/* Left: TOC panel */}
      <div className="w-56 shrink-0 border-r border-border flex flex-col overflow-hidden">
        <div className="px-3 py-2 border-b border-border">
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            Chapters
          </span>
        </div>

        {tocLoading && (
          <div className="flex flex-col gap-2 p-3">
            {[1, 2, 3, 4, 5].map((i) => (
              <Skeleton key={i} className="h-4 w-full" />
            ))}
          </div>
        )}

        {tocError && (
          <div className="p-3">
            <p className="text-xs text-destructive">Could not load chapters.</p>
            <button
              onClick={() => void refetchToc()}
              className="mt-1 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            >
              <RotateCcw size={10} />
              Retry
            </button>
          </div>
        )}

        {toc && toc.length === 0 && (
          <div className="p-3">
            <p className="text-xs text-muted-foreground">No chapters found.</p>
          </div>
        )}

        {toc && toc.length > 0 && (
          <div className="flex-1 overflow-auto">
            <ul className="py-1">
              {toc.map((item) => (
                <li key={item.chapter_index}>
                  <button
                    onClick={() => setActiveChapter(item.chapter_index)}
                    className={cn(
                      "w-full px-3 py-2 text-left text-xs leading-snug transition-colors",
                      activeChapter === item.chapter_index
                        ? "bg-primary/10 text-foreground font-medium"
                        : "text-muted-foreground hover:bg-accent hover:text-foreground",
                    )}
                  >
                    <span className="line-clamp-2">{item.title}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* Right: Chapter content */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Chapter loading state: skeleton lines */}
        {chapterLoading && (
          <div className="flex-1 overflow-auto px-6 py-4">
            <Skeleton className="mb-4 h-6 w-2/3" />
            {[1, 2, 3, 4, 5, 6, 7, 8].map((i) => (
              <Skeleton key={i} className="mb-3 h-4 w-full" />
            ))}
            <Skeleton className="mb-3 h-4 w-3/4" />
          </div>
        )}

        {/* Chapter error state */}
        {chapterError && !chapterLoading && (
          <div className="flex-1 overflow-auto px-6 py-4">
            <p className="text-sm text-destructive">
              Could not render chapter {activeChapter + 1}.
            </p>
            <button
              onClick={() => void refetchChapter()}
              className="mt-2 flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
            >
              <RotateCcw size={12} />
              Retry
            </button>
          </div>
        )}

        {/* Chapter content */}
        {chapter && !chapterLoading && !chapterError && (
          <div className="flex-1 overflow-auto">
            <div
              className="prose prose-sm dark:prose-invert max-w-none px-6 py-4"
              // Safe: HTML is sanitized server-side by bleach + BeautifulSoup
              // eslint-disable-next-line react/no-danger
              dangerouslySetInnerHTML={{ __html: chapter.html }}
            />
          </div>
        )}

        {/* Prev / Next navigation bar */}
        {toc && toc.length > 0 && (
          <div className="flex items-center justify-between border-t border-border px-4 py-2 shrink-0">
            <button
              onClick={goToPrev}
              disabled={activeChapter === 0}
              className="flex items-center gap-1 rounded px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ChevronLeft size={14} />
              Prev
            </button>

            <span className="text-xs text-muted-foreground tabular-nums">
              {activeChapter + 1} / {totalChapters}
            </span>

            <button
              onClick={goToNext}
              disabled={activeChapter >= totalChapters - 1}
              className="flex items-center gap-1 rounded px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
            >
              Next
              <ChevronRight size={14} />
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
