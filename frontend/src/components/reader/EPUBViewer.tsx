/**
 * EPUBViewer — Two-column chapter reader for EPUB documents
 *
 * Left panel: scrollable chapter TOC with active chapter highlighted.
 * Right panel: sanitized chapter HTML rendered in a Tailwind prose div.
 *
 * SelectionActionBar integration: the parent DocumentReader already wraps
 * its entire left panel in a ref — EPUBViewer is mounted inside that ref,
 * so selection events bubble up automatically without extra wiring here.
 */

import { useQuery } from "@tanstack/react-query"
import { ChevronLeft, ChevronRight, PanelLeftClose, PanelLeftOpen, RotateCcw } from "lucide-react"
import { useState } from "react"
import { cn } from "@/lib/utils"
import { Skeleton } from "@/components/ui/skeleton"
import { apiGet } from "@/lib/apiClient"

import type { components } from "@/types/api"
import { useResizablePanel } from "@/hooks/useResizablePanel"
import { PanelResizer } from "./PanelResizer"

type EpubTocItem = components["schemas"]["EpubChapterTocItem"]
type EpubChapter = components["schemas"]["EpubChapterResponse"]

async function fetchToc(documentId: string): Promise<EpubTocItem[]> {
  const data = await apiGet<{ chapters: EpubTocItem[] }>(
    `/documents/${documentId}/epub/toc`,
  )
  return data.chapters
}

const fetchChapter = (
  documentId: string,
  chapterIndex: number,
): Promise<EpubChapter> =>
  apiGet<EpubChapter>(`/documents/${documentId}/epub/chapter/${chapterIndex}`)

interface EPUBViewerProps {
  documentId: string
}

export function EPUBViewer({ documentId }: EPUBViewerProps) {
  const tocPanel = useResizablePanel({
    storageKey: "luminary-epub-toc",
    defaultWidth: 224,
    minWidth: 160,
    maxWidth: 480,
    side: "right",
  })
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

  /**
   * Keep the book's own links inside the book.
   *
   * Chapter HTML is injected verbatim, so an EPUB's contents page carries real
   * anchors -- `#chap01`, `chapter3.xhtml`. Left alone the browser follows them,
   * the router sees a path it does not know, and the reader is thrown out to
   * the library mid-book. Same-document targets scroll; anything else that is
   * not an external link is swallowed rather than allowed to navigate away.
   */
  function handleContentClick(e: React.MouseEvent<HTMLDivElement>) {
    const anchor = (e.target as HTMLElement).closest("a")
    if (!anchor) return
    const href = anchor.getAttribute("href")
    if (!href) return
    if (/^(https?:|mailto:)/i.test(href)) return // real outbound link, let it open

    e.preventDefault()
    const hash = href.startsWith("#") ? href.slice(1) : href.split("#")[1]
    if (!hash) return
    const target =
      e.currentTarget.querySelector(`#${CSS.escape(hash)}`) ??
      e.currentTarget.querySelector(`[name="${CSS.escape(hash)}"]`)
    target?.scrollIntoView({ behavior: "smooth", block: "start" })
  }

  return (
    <div className="flex h-full overflow-hidden">
      {/* Left: TOC panel */}
      {tocPanel.collapsed ? (
        <button
          type="button"
          onClick={tocPanel.toggle}
          aria-label="Show chapters"
          title="Show chapters"
          className="flex h-full w-8 shrink-0 items-start justify-center border-r border-border pt-3 text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <PanelLeftOpen size={16} />
        </button>
      ) : (
      <div
        className="shrink-0 border-r border-border flex flex-col overflow-hidden"
        style={{ width: tocPanel.width }}
      >
        <div className="flex items-center justify-between px-3 py-2 border-b border-border">
          <span className="lum-eyebrow">
            Chapters
          </span>
          <button
            type="button"
            onClick={tocPanel.toggle}
            aria-label="Hide chapters"
            title="Hide chapters"
            className="text-muted-foreground hover:text-foreground"
          >
            <PanelLeftClose size={14} />
          </button>
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
      )}
      {!tocPanel.collapsed && (
        <PanelResizer
          onPointerDown={tocPanel.onPointerDown}
          dragging={tocPanel.dragging}
          label="Resize chapters panel"
        />
      )}

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
              dangerouslySetInnerHTML={{ __html: chapter.html }}
              onClick={handleContentClick}
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
