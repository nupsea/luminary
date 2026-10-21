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
import { Bookmark, ChevronLeft, ChevronRight, PanelLeftClose, PanelLeftOpen, RotateCcw, X } from "lucide-react"
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react"
import { cn } from "@/lib/utils"
import { Skeleton } from "@/components/ui/skeleton"
import { apiGet } from "@/lib/apiClient"
import { settleIntoView } from "@/lib/citation/settleIntoView"

import type { components } from "@/types/api"
import { useResizablePanel } from "@/hooks/useResizablePanel"
import { PanelResizer } from "./PanelResizer"
import { usePanelZoomStore } from "@/store/panelZoomStore"
import { PanelZoomResetButton } from "@/components/PanelZoomResetButton"
import { EPUB_BLOCK_SELECTOR, READING_LINE_PX, blockAtLine, samePlace, type EpubPlace } from "./epubPlace"

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
  /** Where the book opens; read once, on mount. */
  initialPlace?: EpubPlace | null
  bookmark?: EpubPlace | null
  onBookmarkChange?: (place: EpubPlace | null) => void
  /** The place the reader has scrolled to, and the title of its chapter. */
  onReadingPlaceChange?: (place: EpubPlace, chapterTitle: string) => void
}

export interface EPUBViewerHandle {
  goTo: (place: EpubPlace) => void
}

/** Where to scroll once a chapter has rendered: a block, or an element the book links to. */
type Target = { chapter: number; block: number } | { chapter: number; anchor: string }

function blocksIn(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(EPUB_BLOCK_SELECTOR))
}

export const EPUBViewer = forwardRef<EPUBViewerHandle, EPUBViewerProps>(function EPUBViewer(
  { documentId, initialPlace = null, bookmark = null, onBookmarkChange, onReadingPlaceChange },
  ref,
) {
  const readerZoom = usePanelZoomStore((s) => s.getZoom("reader"))
  const { attachPanel: attachTocPanel, ...tocPanel } = useResizablePanel({
    storageKey: "luminary-epub-toc",
    defaultWidth: 224,
    minWidth: 160,
    maxWidth: 480,
    side: "right",
  })
  const [activeChapter, setActiveChapter] = useState(initialPlace?.chapter ?? 0)
  const [currentBlock, setCurrentBlock] = useState(0)
  const [zoomedImgSrc, setZoomedImgSrc] = useState<string | null>(null)
  const targetRef = useRef<Target | null>(initialPlace)
  const [jumpNonce, setJumpNonce] = useState(0)

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
    enabled: activeChapter < (toc?.length ?? 0),
  })

  const totalChapters = toc?.length ?? 0
  const contentContainerRef = useRef<HTMLDivElement>(null)
  const chapterTitle = toc?.[activeChapter]?.title ?? ""

  // A saved place can outlive a re-import that produced fewer chapters.
  useEffect(() => {
    if (toc && toc.length > 0 && activeChapter >= toc.length) {
      targetRef.current = null
      setActiveChapter(0)
    }
  }, [toc, activeChapter])

  const goTo = useCallback((target: Target) => {
    targetRef.current = target
    setActiveChapter(target.chapter)
    setJumpNonce((n) => n + 1)
  }, [])

  useImperativeHandle(ref, () => ({ goTo }), [goTo])

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

  // Read through a ref so a parent re-render cannot restart a settle in progress.
  const reportingRef = useRef({ activeChapter, chapterTitle, onReadingPlaceChange })
  useEffect(() => {
    reportingRef.current = { activeChapter, chapterTitle, onReadingPlaceChange }
  })
  const reportPlace = useCallback(() => {
    const container = contentContainerRef.current
    // A hidden Book View has no layout: every top reads 0, which names the last block.
    if (!container || container.getClientRects().length === 0) return
    const blocks = blocksIn(container)
    const line = container.getBoundingClientRect().top + READING_LINE_PX
    const block = blockAtLine(blocks.length, (i) => blocks[i].getBoundingClientRect().top, line)
    const { activeChapter: chapterIndex, chapterTitle: title, onReadingPlaceChange: report } =
      reportingRef.current
    setCurrentBlock(block)
    report?.({ chapter: chapterIndex, block }, title)
  }, [])

  // Once a chapter has rendered, go to the place asked for, or report where the
  // reader now is. Settled rather than scrolled once: images above the target
  // load and push it down.
  useEffect(() => {
    const container = contentContainerRef.current
    if (!chapter || !container) return
    const target = targetRef.current
    if (!target || target.chapter !== activeChapter) {
      reportPlace()
      return
    }
    targetRef.current = null
    const offset = (el: HTMLElement) =>
      el.getBoundingClientRect().top - container.getBoundingClientRect().top - READING_LINE_PX / 2
    return settleIntoView<HTMLElement>({
      find: () =>
        "anchor" in target
          ? container.querySelector<HTMLElement>(`#${CSS.escape(target.anchor)}`)
          : (blocksIn(container)[target.block] ?? null),
      distance: offset,
      centre: (el) => container.scrollBy({ top: offset(el), behavior: "instant" }),
      schedule: (fn, ms) => window.setTimeout(fn, ms),
      cancel: (handle) => window.clearTimeout(handle),
      tolerancePx: 4,
      userEventsTarget: container,
    })
  }, [chapter, activeChapter, jumpNonce, reportPlace])

  const scrollFrameRef = useRef<number | null>(null)
  useEffect(() => () => {
    if (scrollFrameRef.current != null) window.cancelAnimationFrame(scrollFrameRef.current)
  }, [])
  const handleContentScroll = useCallback(() => {
    if (scrollFrameRef.current != null) return
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      scrollFrameRef.current = null
      reportPlace()
    })
  }, [reportPlace])

  // Images loading above the reading line move the text without a scroll event,
  // and the place saved would then be a block away from what is on screen.
  useEffect(() => {
    const content = contentContainerRef.current?.firstElementChild
    if (!chapter || !content) return
    const observer = new ResizeObserver(handleContentScroll)
    observer.observe(content)
    return () => observer.disconnect()
  }, [chapter, handleContentScroll])

  // Mark the bookmarked block, as the PDF viewer marks its bookmarked page.
  useEffect(() => {
    const container = contentContainerRef.current
    if (!chapter || !container || bookmark?.chapter !== activeChapter) return
    const el = blocksIn(container)[bookmark.block]
    el?.setAttribute("data-bookmark", "")
    return () => el?.removeAttribute("data-bookmark")
  }, [chapter, activeChapter, bookmark])

  const here: EpubPlace = { chapter: activeChapter, block: currentBlock }
  const atBookmark = samePlace(bookmark, here)
  // I-67
  const chapterHtml = useMemo(() => ({ __html: chapter?.html ?? "" }), [chapter?.html])

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
    // The backend names the chapter that holds a link's target in another chapter.
    const chapterAttr = anchor.getAttribute("data-chapter")
    if (chapterAttr != null) {
      const chapterIndex = Number(chapterAttr)
      goTo(hash ? { chapter: chapterIndex, anchor: hash } : { chapter: chapterIndex, block: 0 })
      return
    }
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
          <div ref={contentContainerRef} className="flex-1 overflow-auto" onScroll={handleContentScroll}>
            <div
              className={cn(
                "epub-reader-content prose prose-sm dark:prose-invert max-w-3xl mx-auto px-6 py-6",
                // Books use <pre> for verse, not only code. Prose pairs pale
                // `pre` text with a dark background, which does not hold here.
                "prose-pre:bg-muted/50 prose-pre:text-foreground prose-pre:border prose-pre:border-border",
                // Prose wraps inline code in literal backticks; a printed book has none.
                "prose-code:before:content-none prose-code:after:content-none",
              )}
              style={{ fontSize: `${readerZoom}rem` }}
              // Safe: HTML is sanitized server-side by bleach + BeautifulSoup
              dangerouslySetInnerHTML={chapterHtml}
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

            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground tabular-nums">
                {activeChapter + 1} / {totalChapters}
              </span>
              {onBookmarkChange && (
                <button
                  type="button"
                  className={cn("rounded p-1 hover:bg-accent", atBookmark ? "text-red-600" : "text-muted-foreground")}
                  onClick={() => onBookmarkChange(atBookmark ? null : here)}
                  title={atBookmark ? "Remove bookmark" : bookmark != null ? "Move bookmark here" : "Bookmark this place"}
                  aria-label={atBookmark ? "Remove bookmark" : "Bookmark this place"}
                  aria-pressed={atBookmark}
                >
                  <Bookmark className="h-3.5 w-3.5" fill={atBookmark ? "currentColor" : "none"} />
                </button>
              )}
              {bookmark != null && !atBookmark && (
                <button
                  type="button"
                  className="flex items-center gap-0.5 rounded px-1 py-0.5 text-xs text-red-600 hover:bg-accent tabular-nums"
                  onClick={() => goTo(bookmark)}
                  title={`Go to your bookmark (chapter ${bookmark.chapter + 1})`}
                  aria-label={`Go to your bookmark, chapter ${bookmark.chapter + 1}`}
                >
                  <Bookmark className="h-3 w-3" fill="currentColor" />
                  {bookmark.chapter + 1}
                </button>
              )}
              <PanelZoomResetButton panelId="reader" />
            </div>

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
})
