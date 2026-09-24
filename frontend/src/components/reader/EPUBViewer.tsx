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
import { ChevronLeft, ChevronRight, PanelLeftClose, PanelLeftOpen, RotateCcw, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { cn } from "@/lib/utils"
import { Skeleton } from "@/components/ui/skeleton"
import { apiGet } from "@/lib/apiClient"

import type { components } from "@/types/api"
import { useResizablePanel } from "@/hooks/useResizablePanel"
import { PanelResizer } from "./PanelResizer"
import { usePanelZoomStore } from "@/store/panelZoomStore"

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

// Keyboard navigation shortcuts: ArrowRight / PageDown for next chapter, ArrowLeft / PageUp for previous
export function handleEpubKeyboardShortcut(
  e: {
    key: string
    target?: EventTarget | null
    preventDefault?: () => void
  },
  state: {
    activeChapter: number
    totalChapters: number
    zoomedImgSrc: string | null
    onNextChapter: () => void
    onPrevChapter: () => void
    onCloseLightbox: () => void
  },
): boolean {
  if (
    typeof HTMLElement !== "undefined" &&
    (e.target instanceof HTMLInputElement ||
      e.target instanceof HTMLTextAreaElement ||
      (e.target as HTMLElement)?.isContentEditable)
  ) {
    return false
  }

  if (e.key === "Escape") {
    if (state.zoomedImgSrc) {
      e.preventDefault?.()
      state.onCloseLightbox()
      return true
    }
  }

  if (e.key === "ArrowRight" || e.key === "PageDown") {
    if (state.activeChapter < state.totalChapters - 1) {
      e.preventDefault?.()
      state.onNextChapter()
      return true
    }
  } else if (e.key === "ArrowLeft" || e.key === "PageUp") {
    if (state.activeChapter > 0) {
      e.preventDefault?.()
      state.onPrevChapter()
      return true
    }
  }

  return false
}

interface EPUBViewerProps {
  documentId: string
}

export function EPUBViewer({ documentId }: EPUBViewerProps) {
  const readerZoom = usePanelZoomStore((s) => s.getZoom("reader"))
  const { attachPanel: attachTocPanel, ...tocPanel } = useResizablePanel({
    storageKey: "luminary-epub-toc",
    defaultWidth: 224,
    minWidth: 160,
    maxWidth: 480,
    side: "right",
  })
  const [activeChapter, setActiveChapter] = useState(0)
  const [zoomedImgSrc, setZoomedImgSrc] = useState<string | null>(null)

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
  const contentContainerRef = useRef<HTMLDivElement>(null)

  function goToPrev() {
    if (activeChapter > 0) setActiveChapter((c) => c - 1)
  }

  function goToNext() {
    if (activeChapter < totalChapters - 1) setActiveChapter((c) => c + 1)
  }

  // Scroll to top of content when active chapter changes
  useEffect(() => {
    contentContainerRef.current?.scrollTo({ top: 0, behavior: "instant" })
  }, [activeChapter])

  // Keyboard navigation shortcuts: ArrowRight / PageDown for next chapter, ArrowLeft / PageUp for previous
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      handleEpubKeyboardShortcut(e, {
        activeChapter,
        totalChapters,
        zoomedImgSrc,
        onNextChapter: () => setActiveChapter((c) => c + 1),
        onPrevChapter: () => setActiveChapter((c) => c - 1),
        onCloseLightbox: () => setZoomedImgSrc(null),
      })
    }

    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [activeChapter, totalChapters, zoomedImgSrc])

  /**
   * Keep the book's own links inside the book: chapter HTML is injected
   * verbatim, so its anchors would otherwise navigate the router away.
   * Also captures diagram clicks to zoom in lightbox.
   */
  function handleContentClick(e: React.MouseEvent<HTMLDivElement>) {
    const img = (e.target as HTMLElement).closest("img")
    if (img && img.src) {
      setZoomedImgSrc(img.src)
      return
    }

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
    <div data-zoom-panel="reader" className="flex h-full overflow-hidden">
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
        ref={attachTocPanel}
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
          <div ref={contentContainerRef} className="flex-1 overflow-auto">
            <div
              className={cn(
                "epub-reader-content prose prose-sm dark:prose-invert max-w-3xl mx-auto px-6 py-6",
                // Books use <pre> for verse, not only code. Prose pairs pale
                // `pre` text with a dark background, which does not hold here.
                "prose-pre:bg-muted/50 prose-pre:text-foreground prose-pre:border prose-pre:border-border",
              )}
              style={{ fontSize: `${readerZoom}rem` }}
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

      {/* High-resolution diagram lightbox */}
      {zoomedImgSrc && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in duration-150"
          onClick={() => setZoomedImgSrc(null)}
        >
          <div className="relative max-h-[92vh] max-w-[92vw] overflow-hidden rounded-lg border border-border/80 bg-background/95 p-2 shadow-2xl">
            <button
              type="button"
              onClick={() => setZoomedImgSrc(null)}
              className="absolute top-3 right-3 rounded-full bg-background/80 p-1.5 text-muted-foreground hover:text-foreground backdrop-blur-sm shadow z-10"
              title="Close"
            >
              <X size={18} />
            </button>
            <img
              src={zoomedImgSrc}
              alt="Expanded diagram"
              className="max-h-[85vh] max-w-[85vw] object-contain rounded"
            />
          </div>
        </div>
      )}
    </div>
  )
}
