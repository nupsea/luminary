import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react"
import * as pdfjsLib from "pdfjs-dist"
import { AnnotationLayer, TextLayer } from "pdfjs-dist"
import type { PDFDocumentProxy, PDFPageProxy } from "pdfjs-dist"
import "pdfjs-dist/web/pdf_viewer.css"
import { ChevronLeft, ChevronRight, Minus, Moon, PanelLeftClose, PanelLeftOpen, Plus, Search, Sun } from "lucide-react"
import { API_BASE, PDFJS_WORKER_URL } from "@/lib/config"
import { useIsDark } from "@/hooks/useIsDark"
import { useResizablePanel } from "@/hooks/useResizablePanel"
import { PanelResizer } from "./PanelResizer"
import { Skeleton } from "@/components/ui/skeleton"
import type { AnnotationItem, SectionItem } from "./types"
import {
  type OutlineEntry,
  buildFontTOC,
  flattenOutline,
  looksLikeHeading,
  resolveOutline,
  shouldUseOutline,
} from "./pdfTocUtils"
import { usableSections } from "./sectionTitle"
import { createLinkService } from "./pdfLinkService"
import { PdfSearchBar } from "./PdfSearchBar"
import { ZOOM_PRESETS, ZOOM_STOPS, type PageMatch, activeMatchIndexForPage, buildGlobalMatches, findMatchIndices, formatMatchCounts, printedPageLabel, stepZoom } from "./pdfSearchUtils"
import { clearOverlays, computeHighlightRects, renderOverlayDivs } from "./pdfHighlightOverlay"

// Set worker once at module load
pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER_URL

/**
 * Build span-offset parts from the text layer for highlight rect computation.
 * Reused by both annotation and search highlight functions.
 */
function buildTextParts(textLayerDiv: HTMLDivElement) {
  const spans = Array.from(textLayerDiv.querySelectorAll("span")) as HTMLSpanElement[]
  if (spans.length === 0) return null
  const parts: { span: HTMLSpanElement; start: number; end: number }[] = []
  let offset = 0
  for (let i = 0; i < spans.length; i++) {
    if (i > 0) offset += 1 // space separator (matches browser selection toString())
    const text = spans[i].textContent ?? ""
    parts.push({ span: spans[i], start: offset, end: offset + text.length })
    offset += text.length
  }
  const fullText = spans.map((s) => s.textContent ?? "").join(" ")
  return { spans, parts, fullText }
}

/**
 * Build a whitespace-stripped view of the text plus a map from each compact
 * index back to its offset in the original text.
 */
function buildWhitespaceMap(fullText: string): { compact: string; map: number[] } {
  let compact = ""
  const map: number[] = []
  for (let i = 0; i < fullText.length; i++) {
    if (!/\s/.test(fullText[i])) {
      compact += fullText[i]
      map.push(i)
    }
  }
  return { compact, map }
}

/** Apply annotation highlight overlays using absolutely-positioned divs. */
function applyPdfHighlights(
  textLayerDiv: HTMLDivElement,
  overlayContainer: HTMLDivElement,
  annotations: AnnotationItem[],
  currentPage: number,
  sections: SectionItem[],
) {
  clearOverlays(overlayContainer, "data-pdf-highlight")

  if (annotations.length === 0) return

  // 1. Filter annotations for current page efficiently
  const sectionMap = new Map<string, SectionItem>()
  for (const s of sections) sectionMap.set(s.id, s)

  const pageAnnotations = annotations.filter((ann) => {
    if (ann.page_number != null) return ann.page_number === currentPage
    const sec = sectionMap.get(ann.section_id)
    if (sec) {
      const start = sec.page_start || 1
      const end = sec.page_end || start
      return currentPage >= start && currentPage <= end
    }
    return true
  })

  if (pageAnnotations.length === 0) return

  // Sort by start_offset so we find occurrences in document order.
  // This is critical for the "find next occurrence" strategy to work.
  const sortedAnnotations = [...pageAnnotations].sort((a, b) => (a.start_offset || 0) - (b.start_offset || 0))

  const textData = buildTextParts(textLayerDiv)
  if (!textData) return
  const { spans, parts, fullText } = textData

  const containerRect = overlayContainer.getBoundingClientRect()

  // Whitespace-insensitive view of the text layer, computed once. The text
  // layer joins spans with single spaces, but a selection captured via
  // selection.toString() may differ in spacing around bullets, line breaks,
  // and punctuation (e.g. "data. •" in the layer vs "data.•" in the
  // selection). Matching on whitespace-stripped text and mapping back to the
  // full offset tolerates those differences.
  const { compact: compactFull, map: compactMap } = buildWhitespaceMap(fullText)

  const usedFullOffsets = new Set<number>()
  const usedCompactOffsets = new Set<number>()

  for (const ann of sortedAnnotations) {
    const searchVal = ann.selected_text
    if (!searchVal) continue

    let idx = -1
    let matchEnd = -1
    let searchStart = 0

    // Fast path: next unused exact occurrence in the joined text.
    while (true) {
      idx = fullText.indexOf(searchVal, searchStart)
      if (idx < 0) break
      if (!usedFullOffsets.has(idx)) {
        usedFullOffsets.add(idx)
        break
      }
      searchStart = idx + 1
    }

    if (idx >= 0) {
      matchEnd = idx + searchVal.length
    } else {
      // Fallback: whitespace-insensitive next-occurrence search.
      const compactSearch = searchVal.replace(/\s+/g, "")
      if (!compactSearch) continue

      let cIdx = -1
      let cStart = 0
      while (true) {
        cIdx = compactFull.indexOf(compactSearch, cStart)
        if (cIdx < 0) break
        if (!usedCompactOffsets.has(cIdx)) {
          usedCompactOffsets.add(cIdx)
          break
        }
        cStart = cIdx + 1
      }

      if (cIdx < 0) continue

      idx = compactMap[cIdx]
      matchEnd = compactMap[cIdx + compactSearch.length - 1] + 1
    }

    const bgColor = PDF_HIGHLIGHT_COLORS[ann.color] ?? PDF_HIGHLIGHT_COLORS.yellow

    const rects = computeHighlightRects(spans, parts, idx, matchEnd, containerRect)
    renderOverlayDivs(overlayContainer, rects, bgColor, "data-pdf-highlight", ann.id)
  }
}

/** Apply search-match highlights as overlay divs. Returns count of matches found. */
function applySearchHighlights(
  textLayerDiv: HTMLDivElement,
  overlayContainer: HTMLDivElement,
  query: string,
  activeMatchIndex: number,
): number {
  clearOverlays(overlayContainer, "data-search-highlight")

  if (!query) return 0

  const textData = buildTextParts(textLayerDiv)
  if (!textData) return 0
  const { spans, parts, fullText } = textData

  const matchIndices = findMatchIndices(fullText, query)
  if (matchIndices.length === 0) return 0

  const containerRect = overlayContainer.getBoundingClientRect()
  const queryLen = query.length

  for (let mi = 0; mi < matchIndices.length; mi++) {
    const matchStart = matchIndices[mi]
    const matchEnd = matchStart + queryLen
    const isActive = mi === activeMatchIndex

    const color = isActive ? "rgba(249, 115, 22, 0.6)" : "rgba(250, 204, 21, 0.4)"
    const rects = computeHighlightRects(spans, parts, matchStart, matchEnd, containerRect)
    renderOverlayDivs(overlayContainer, rects, color, "data-search-highlight", undefined, isActive)
  }

  // Scroll active match into view
  const activeMark = overlayContainer.querySelector("[data-active-search-match]")
  if (activeMark) {
    activeMark.scrollIntoView({ behavior: "smooth", block: "center" })
  }

  return matchIndices.length
}

const PDF_HIGHLIGHT_COLORS: Record<string, string> = {
  yellow: "rgba(250, 204, 21, 0.4)",  // yellow-400
  green: "rgba(74, 222, 128, 0.4)",   // green-400
  blue: "rgba(96, 165, 250, 0.4)",    // blue-400
  pink: "rgba(244, 114, 182, 0.4)",   // pink-400
}

interface PDFViewerProps {
  documentId: string
  sections: SectionItem[]
  /**
   * Sheet -> the number printed on it, derived at ingestion.
   *
   * pdf.js only reports labels a PDF *declares*. A book that merely prints its
   * page numbers declares none, so without this the footer counts sheets while
   * the citation that opened the document names the printed page -- the two
   * disagreeing by a constant, which is the confusion this whole thread began
   * with.
   */
  pageLabels?: Record<string, string>
  initialPage?: number  // navigate to this page after PDF loads (from citation deep-link)
  annotations?: AnnotationItem[]
  highlightsVisible?: boolean
  onPageChange?: (page: number) => void
}

export interface PDFViewerHandle {
  goToPage: (n: number) => void
}

type LoadStatus = "loading" | "error" | "ready"

export const PDFViewer = forwardRef<PDFViewerHandle, PDFViewerProps>(
  function PDFViewer({ documentId, sections, pageLabels, initialPage, annotations = [], highlightsVisible = true, onPageChange }, ref) {
    const [pdfDoc, setPdfDoc] = useState<PDFDocumentProxy | null>(null)
    const [currentPage, setCurrentPage] = useState(1)
    const [totalPages, setTotalPages] = useState(0)
    const [zoom, setZoom] = useState(1.0)
    const [loadStatus, setLoadStatus] = useState<LoadStatus>("loading")
    const [pageInput, setPageInput] = useState("1")

    // The PDF renders to a raster canvas, so it ignores the app theme. In dark
    // mode we invert the canvas to a dark page by default; the user can toggle it
    // off for figure-heavy pages, where inversion turns photos into negatives.
    const isDark = useIsDark()
    const toc = useResizablePanel({
      storageKey: "luminary-pdf-toc",
      defaultWidth: 224,
      minWidth: 160,
      maxWidth: 480,
      side: "right",
    })
    const [darkPage, setDarkPage] = useState(isDark)
    useEffect(() => setDarkPage(isDark), [isDark])
    // Softened invert (not a full 1.0) so the page is dark-gray on light-gray
    // rather than harsh #000/#fff; hue-rotate keeps colored links roughly right.
    const canvasFilter = darkPage ? "invert(0.9) hue-rotate(180deg)" : undefined

    const pageCommitTimer = useRef<number | null>(null)
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const textLayerRef = useRef<HTMLDivElement>(null)
    const highlightOverlayRef = useRef<HTMLDivElement>(null)
    const annotationLayerRef = useRef<HTMLDivElement>(null)
    const nextCanvasRef = useRef<HTMLCanvasElement>(null)
    const scrollAreaRef = useRef<HTMLDivElement>(null)
    // Bumped after each text layer render to trigger highlight application
    const [textLayerVersion, setTextLayerVersion] = useState(0)
    // PDF built-in outline (bookmarks) -- preferred over backend sections when available
    const [pdfOutline, setPdfOutline] = useState<OutlineEntry[]>([])
    // Refs for annotations/visibility so the render effect can apply highlights inline
    const annotationsRef = useRef(annotations)
    annotationsRef.current = annotations
    const highlightsVisibleRef = useRef(highlightsVisible)
    highlightsVisibleRef.current = highlightsVisible
    // Relabel rather than drop: an anchor-id heading still navigates, and
    // filtering these out emptied the contents panel entirely.
    const tocSections = useMemo(() => usableSections(sections), [sections])
    const sectionsRef = useRef(sections)
    sectionsRef.current = sections

    // ── Search state ──────────────────────────────────────────────────
    const [searchOpen, setSearchOpen] = useState(false)
    const [zoomOpen, setZoomOpen] = useState(false)
    const zoomPopoverRef = useRef<HTMLDivElement | null>(null)
    // What the box shows, and what the search actually runs on. They are
    // separate because every change of the second one re-extracts the whole
    // document: typing a seven-letter word launched seven full passes over 613
    // pages, each clearing and redrawing the highlights 62 times as its batches
    // landed. The box stays instant; the search waits for a pause in typing,
    // the same way the page field already does.
    const [searchInput, setSearchInput] = useState("")
    const [searchQuery, setSearchQuery] = useState("")
    const [globalMatches, setGlobalMatches] = useState<PageMatch[]>([])
    const [globalMatchIndex, setGlobalMatchIndex] = useState(-1)
    const pageTextCacheRef = useRef<Map<number, string>>(new Map())
    // Track how many pages have been extracted so far (for progressive search)
    const [extractedPageCount, setExtractedPageCount] = useState(0)
    // The numbers printed on the sheets, when the PDF says they differ from
    // the sheets' positions. Null on a document that defines none.
    const [declaredLabels, setDeclaredLabels] = useState<string[] | null>(null)
    // What the overlay currently shows, so an identical redraw is skipped.
    const lastHighlightRef = useRef("")

    // Expose goToPage for parent (section list page-jump badges)
    useImperativeHandle(
      ref,
      () => ({
        goToPage(n: number) {
          if (!pdfDoc) return
          const clamped = Math.max(1, Math.min(n, totalPages))
          setCurrentPage(clamped)
          setPageInput(String(clamped))
        },
      }),
      [pdfDoc, totalPages],
    )

    // Load the PDF document
    useEffect(() => {
      let cancelled = false
      setLoadStatus("loading")
      setPdfDoc(null)
      setPdfOutline([])   // clear stale outline so backend sections show while new one resolves
      setCurrentPage(1)
      setPageInput("1")
      setTotalPages(0)
      setDeclaredLabels(null)
      // Clear search state and text cache for new document
      pageTextCacheRef.current = new Map()
      setExtractedPageCount(0)
      closeSearch()

      const task = pdfjsLib.getDocument({
        url: `${API_BASE}/documents/${documentId}/file`,
        // Enable HTTP range requests so pdfjs can fetch only the byte ranges
        // it needs (e.g. xref table + first page) instead of downloading the
        // entire PDF before showing anything. Dramatically speeds up large PDFs.
        disableRange: false,
        disableStream: false,
        rangeChunkSize: 65536, // 64 KB chunks
      })

      task.promise
        .then(async (doc) => {
          if (cancelled) return
          setPdfDoc(doc)
          setTotalPages(doc.numPages)
          // Set ready immediately so the page render effect fires right away.
          // Auto-fit and TOC scan are deferred so they don't delay first paint.
          setLoadStatus("ready")

          // Defer auto-fit and TOC after a tick so the canvas renders first
          setTimeout(async () => {
            if (cancelled) return

            // A book numbers its front matter separately, so the sheet's
            // position is not the page number printed on it. Deferred with the
            // rest: the footer is correct without it, just less specific.
            try {
              const labels = await doc.getPageLabels()
              if (!cancelled) setDeclaredLabels(labels)
            } catch {
              // non-fatal; the footer falls back to counting sheets
            }

            // Auto-fit: compute zoom so the first page fills the scroll area width
            try {
              const page = await doc.getPage(1)
              const naturalVp = page.getViewport({ scale: 1.0 })
              page.cleanup()
              if (scrollAreaRef.current && naturalVp.width > 0) {
                const available = scrollAreaRef.current.clientWidth - 32 // 2 x p-4
                if (available > 0) setZoom(available / naturalVp.width)
              }
            } catch {
              // non-fatal; zoom stays at 1.0
            }

            if (cancelled) return

            // ── TOC source determination ─────────────────────────────────────
            try {
              const rawOutline = await doc.getOutline()
              if (rawOutline && rawOutline.length > 0 && !cancelled) {
                const resolved = await resolveOutline(doc, rawOutline, 1)
                if (!cancelled) {
                  const flat = flattenOutline(resolved).filter(e => looksLikeHeading(e.title))
                  const navigable = flat.filter(e => e.page > 0).sort((a, b) => a.page - b.page)
                  const unresolved = flat.filter(e => e.page === 0)
                  setPdfOutline([...navigable, ...unresolved])
                }
              } else if (!cancelled) {
                // Rule 2: no native outline — scan font sizes (expensive, deferred)
                const fontToc = await buildFontTOC(doc, () => cancelled)
                if (!cancelled && fontToc.length > 0) setPdfOutline(fontToc)
              }
            } catch {
              // non-fatal; TOC panel falls back to backend sections
            }
          }, 100)
        })
        .catch(() => {
          if (!cancelled) setLoadStatus("error")
        })

      return () => {
        cancelled = true
        task.destroy().catch(() => undefined)
      }
    }, [documentId])

    // navigate to initialPage once the PDF is loaded or when initialPage changes
    useEffect(() => {
      if (!initialPage || loadStatus !== "ready" || !totalPages) return
      if (initialPage >= 1 && initialPage <= totalPages) {
        setCurrentPage(initialPage)
        setPageInput(String(initialPage))
      }
    }, [initialPage, loadStatus, totalPages])

    // Render the current page + pre-render next for fast navigation
    useEffect(() => {
      if (!pdfDoc || loadStatus !== "ready") return

      let cancelled = false
      let activeTextLayer: TextLayer | null = null
      // Track active render tasks so cleanup can cancel them and avoid the
      // "Cannot use the same canvas during multiple render() operations" error.
      const activeRenderTasks: Array<{ cancel: () => void }> = []

      async function renderPage(
        pageNum: number,
        canvas: HTMLCanvasElement | null,
        textLayerDiv: HTMLDivElement | null,
        annotationLayerDiv: HTMLDivElement | null,
      ): Promise<void> {
        if (!canvas || !pdfDoc) return
        let page: PDFPageProxy | null = null
        try {
          page = await pdfDoc.getPage(pageNum)
          if (cancelled) return

          const viewport = page.getViewport({ scale: zoom })

          // The backing store must be sized in DEVICE pixels and then scaled
          // back down via CSS, or a retina display upscales a 1x bitmap and
          // every glyph renders soft. The text and annotation layers keep
          // using `viewport` because they position in CSS pixels.
          const outputScale = window.devicePixelRatio || 1
          canvas.width = Math.floor(viewport.width * outputScale)
          canvas.height = Math.floor(viewport.height * outputScale)
          canvas.style.width = `${Math.floor(viewport.width)}px`
          canvas.style.height = `${Math.floor(viewport.height)}px`

          const ctx = canvas.getContext("2d")
          if (!ctx || cancelled) return

          const renderTask = page.render({
            canvasContext: ctx,
            viewport,
            transform: outputScale === 1 ? undefined : [outputScale, 0, 0, outputScale, 0, 0],
          })
          activeRenderTasks.push(renderTask)
          try {
            await renderTask.promise
          } catch (e: unknown) {
            // RenderingCancelledException is expected when the effect is cleaned up
            if (e instanceof Error && e.name === "RenderingCancelledException") return
            throw e
          }
          if (cancelled) return

          // Yield to browser so the canvas paints immediately before we do expensive text extraction
          await new Promise(resolve => setTimeout(resolve, 0))
          if (cancelled) return

          // Official pdfjs TextLayer -- supports proper drag-to-select across spans.
          // We set --scale-factor CSS var on the container so TextLayer's
          // setLayerDimensions() can compute width/height correctly.
          if (textLayerDiv) {
            // Cancel any previous text layer
            activeTextLayer?.cancel()

            // Clear previous content
            textLayerDiv.replaceChildren()

            // Set the CSS variable that TextLayer needs for sizing
            textLayerDiv.style.setProperty("--scale-factor", String(viewport.scale))

            // Set explicit dimensions and absolute positioning for text layer
            textLayerDiv.style.position = "absolute"
            textLayerDiv.style.top = "0"
            textLayerDiv.style.left = "0"
            textLayerDiv.style.width = `${viewport.width}px`
            textLayerDiv.style.height = `${viewport.height}px`
            textLayerDiv.style.pointerEvents = "auto"
            textLayerDiv.style.zIndex = "10"

            try {
              const textContent = await page.getTextContent()
              if (cancelled) return

              const tl = new TextLayer({
                textContentSource: textContent,
                container: textLayerDiv,
                viewport,
              })
              activeTextLayer = tl

              await tl.render()
              if (!cancelled) {
                // Size the highlight overlay to match the text layer
                const overlayDiv = highlightOverlayRef.current
                if (overlayDiv) {
                  overlayDiv.style.width = `${viewport.width}px`
                  overlayDiv.style.height = `${viewport.height}px`
                  overlayDiv.replaceChildren() // clear stale overlays
                }
                // Apply highlights immediately after text layer is ready
                if (highlightsVisibleRef.current && annotationsRef.current.length > 0 && overlayDiv) {
                  applyPdfHighlights(textLayerDiv, overlayDiv, annotationsRef.current, pageNum, sectionsRef.current)
                }
                setTextLayerVersion((v) => v + 1)
              }
            } catch (err) {
              console.warn("Text layer rendering cancelled/failed", err)
            }
          }

          // Annotation Layer -- handles links (external browser links and internal page jumps)
          if (annotationLayerDiv && !cancelled) {
            annotationLayerDiv.replaceChildren()
            annotationLayerDiv.style.width = `${viewport.width}px`
            annotationLayerDiv.style.height = `${viewport.height}px`
            annotationLayerDiv.style.position = "absolute"
            annotationLayerDiv.style.top = "0"
            annotationLayerDiv.style.left = "0"
            annotationLayerDiv.style.zIndex = "20"
            annotationLayerDiv.style.pointerEvents = "none"
            annotationLayerDiv.style.display = "block"
            annotationLayerDiv.style.setProperty("--scale-factor", String(viewport.scale))
            annotationLayerDiv.setAttribute("data-page-num", String(pageNum))

            // Global styles for standard pdfjs annotation layer appearance
            if (!document.getElementById("pdf-annotation-style")) {
              const style = document.createElement("style")
              style.id = "pdf-annotation-style"
              style.textContent = `
                .annotationLayer {
                  position: absolute !important;
                  top: 0 !important;
                  left: 0 !important;
                  opacity: 1 !important;
                  pointer-events: none !important;
                }
                .annotationLayer section {
                  display: block !important;
                  position: absolute !important;
                  box-sizing: border-box !important;
                  pointer-events: none !important;
                }
                .annotationLayer .linkAnnotation > a {
                  display: block !important;
                  width: 100% !important;
                  height: 100% !important;
                  background-color: rgba(59, 130, 246, 0.05) !important; /* Very subtle blue tint */
                  cursor: pointer !important;
                  pointer-events: auto !important;
                }
                .annotationLayer .linkAnnotation > a:hover {
                  background-color: rgba(59, 130, 246, 0.15) !important; /* Slightly stronger blue on hover */
                }
              `
              document.head.appendChild(style)
            }

            try {
              const annotationsData = await page.getAnnotations()
              if (cancelled) return

              const linkService = createLinkService(pdfDoc, goToPage)

              const al = new AnnotationLayer({
                div: annotationLayerDiv,
                accessibilityManager: null,
                annotationCanvasMap: null,
                annotationEditorUIManager: null,
                page,
                viewport,
                l10n: {
                  async getLanguage() { return "en-US" },
                  async getDirection() { return "ltr" },
                  async get(_key: string, _args: unknown, fallback: string) { return fallback }, // pdf.js l10n args type is untyped
                  async translate(_element: HTMLElement) { /* no-op */ },
                } as any, // pdf.js IL10n interface not exported from pdfjs-dist types
              } as any) // pdf.js AnnotationLayerParameters not fully typed in pdfjs-dist

              await al.render({
                annotations: annotationsData,
                viewport,
                linkService,
                intent: "display",
              } as any)
            } catch (err) {
              console.error("[PDFViewer] failed to render annotation layer", err)
            }
          }
        } finally {
          page?.cleanup()
        }
      }

      void renderPage(currentPage, canvasRef.current, textLayerRef.current, annotationLayerRef.current)
      // Defer pre-rendering next page by 300ms so current page renders first.
      // This makes highlight navigation feel instant — the current page appears
      // right away instead of waiting for two pages to render in parallel.
      const nextPageTimer = currentPage < totalPages
        ? setTimeout(() => {
            if (!cancelled) void renderPage(currentPage + 1, nextCanvasRef.current, null, null)
          }, 300)
        : null

      return () => {
        cancelled = true
        if (nextPageTimer) clearTimeout(nextPageTimer)
        activeTextLayer?.cancel()
        // Cancel all in-progress pdfjs render tasks so the canvas is free
        // for the next effect run. Without this, rapid page/zoom changes cause
        // "Cannot use the same canvas during multiple render() operations".
        for (const task of activeRenderTasks) task.cancel()
      }
    }, [pdfDoc, currentPage, zoom, totalPages, loadStatus])

    // Notify parent of page changes
    useEffect(() => {
      onPageChange?.(currentPage)
    }, [currentPage, onPageChange])

    // Apply annotation highlight overlays after the text layer renders.
    // Only depends on textLayerVersion (bumped after each page render) so it
    // doesn't re-run on unrelated parent re-renders.
    useEffect(() => {
      const textDiv = textLayerRef.current
      const overlayDiv = highlightOverlayRef.current
      if (!textDiv || !overlayDiv || textLayerVersion === 0) return
      if (!highlightsVisible || annotations.length === 0) {
        clearOverlays(overlayDiv, "data-pdf-highlight")
        return
      }
      applyPdfHighlights(textDiv, overlayDiv, annotations, currentPage, sections)
    }, [textLayerVersion, currentPage, annotations, highlightsVisible, sections])

    function goToPage(n: number) {
      const clamped = Math.max(1, Math.min(n, totalPages))
      setCurrentPage(clamped)
      setPageInput(String(clamped))
    }

    function commitPageInput() {
      const n = parseInt(pageInput, 10)
      if (!isNaN(n)) goToPage(n)
    }

    // The page field only committed on blur/Enter, so the spinner arrows (and any
    // edit) changed the number without turning the page. Commit on change too,
    // debounced so typing "38" navigates once to 38 rather than to 3 then 38.
    function handlePageInputChange(value: string) {
      setPageInput(value)
      if (pageCommitTimer.current) window.clearTimeout(pageCommitTimer.current)
      const n = parseInt(value, 10)
      if (isNaN(n)) return
      pageCommitTimer.current = window.setTimeout(() => {
        setCurrentPage(Math.max(1, Math.min(n, totalPages)))
      }, 250)
    }
    function commitPageInputNow() {
      if (pageCommitTimer.current) window.clearTimeout(pageCommitTimer.current)
      commitPageInput()
    }

    // ── Search helpers ────────────────────────────────────────────────

    /** Extract text from a single PDF page and cache it. */
    const extractPageText = useCallback(async (doc: PDFDocumentProxy, pageNum: number): Promise<string> => {
      const cached = pageTextCacheRef.current.get(pageNum)
      if (cached !== undefined) return cached
      const page = await doc.getPage(pageNum)
      try {
        const tc = await page.getTextContent()
        const text = tc.items
          .map((item) => ("str" in item ? item.str : ""))
          .join(" ")
        pageTextCacheRef.current.set(pageNum, text)
        return text
      } finally {
        page.cleanup()
      }
    }, [])

    /** Progressively extract text from all pages and rebuild match list. */
    const extractAllPages = useCallback(async (doc: PDFDocumentProxy, query: string) => {
      const total = doc.numPages
      // Extract in batches of 10 for progressive feedback
      const batchSize = 10
      for (let start = 1; start <= total; start += batchSize) {
        const end = Math.min(start + batchSize - 1, total)
        const promises: Promise<string>[] = []
        for (let p = start; p <= end; p++) {
          promises.push(extractPageText(doc, p))
        }
        await Promise.all(promises)
        setExtractedPageCount(end)
        // Rebuild matches after each batch
        if (query) {
          const matches = buildGlobalMatches(pageTextCacheRef.current, query)
          setGlobalMatches(matches)
          // Set initial match index to first match if not yet set
          setGlobalMatchIndex((prev) => (prev < 0 && matches.length > 0 ? 0 : prev))
        }
        // Yield to main thread between batches to keep UI responsive
        await new Promise((resolve) => setTimeout(resolve, 50))
      }
    }, [extractPageText])

    // Settle the typed text before searching on it. 250ms matches the page
    // field: long enough that a word is typed as one query, short enough that
    // the results feel immediate on pausing.
    useEffect(() => {
      const timer = window.setTimeout(() => setSearchQuery(searchInput), 250)
      return () => window.clearTimeout(timer)
    }, [searchInput])

    // Trigger text extraction when search opens or query changes
    useEffect(() => {
      if (!searchOpen || !searchQuery || !pdfDoc) {
        setGlobalMatches([])
        setGlobalMatchIndex(-1)
        return
      }

      let cancelled = false
      const q = searchQuery

      // Rebuild from cache first (instant for already-extracted pages)
      const cached = buildGlobalMatches(pageTextCacheRef.current, q)
      setGlobalMatches(cached)
      if (cached.length > 0) setGlobalMatchIndex(0)

      // Then progressively extract remaining pages. Once the whole document is
      // cached there is nothing to progress through, and running the batch loop
      // anyway republished the match list 62 times on a 600-page book -- for a
      // second search that changes none of them.
      if (pageTextCacheRef.current.size >= pdfDoc.numPages) {
        setGlobalMatchIndex((prev) => (prev < 0 && cached.length > 0 ? 0 : prev))
        return
      }

      void (async () => {
        await extractAllPages(pdfDoc, q)
        if (!cancelled) {
          const all = buildGlobalMatches(pageTextCacheRef.current, q)
          setGlobalMatches(all)
          setGlobalMatchIndex((prev) => (prev < 0 && all.length > 0 ? 0 : prev))
        }
      })()

      return () => { cancelled = true }
    }, [searchQuery, searchOpen, pdfDoc, extractAllPages])

    // Fit the page to the window, the two zooms a reader actually reaches for.
    // Measured from the page itself rather than a remembered number, so they
    // stay correct after the panel is resized.
    const fitTo = useCallback(
      async (mode: "width" | "page") => {
        if (!pdfDoc || !scrollAreaRef.current) return
        try {
          const page = await pdfDoc.getPage(currentPage)
          const viewport = page.getViewport({ scale: 1.0 })
          page.cleanup()
          const availableWidth = scrollAreaRef.current.clientWidth - 32 // 2 x p-4
          const availableHeight = scrollAreaRef.current.clientHeight - 32
          if (viewport.width <= 0 || availableWidth <= 0) return
          const byWidth = availableWidth / viewport.width
          const byHeight = viewport.height > 0 ? availableHeight / viewport.height : byWidth
          setZoom(mode === "width" ? byWidth : Math.min(byWidth, byHeight))
        } catch {
          // Non-fatal: the zoom simply stays where it is.
        }
      },
      [pdfDoc, currentPage],
    )
    const fitToWidth = useCallback(() => void fitTo("width"), [fitTo])
    const fitToPage = useCallback(() => void fitTo("page"), [fitTo])

    // Which match on this page is the active one. Derived here so the effect
    // below depends on a number rather than on the identity of `globalMatches`,
    // which progressive extraction replaces once per ten-page batch.
    // What the sheet in view is printed as, when that differs from its position.
    const printedLabel = useMemo(() => {
      // The derived map wins: it covers books that print a number without
      // declaring one, which is precisely where the footer used to disagree
      // with the citation. Falls back to what the PDF declares.
      const derived = (pageLabels ?? {})[String(currentPage)]
      if (derived && derived !== String(currentPage)) return derived
      return printedPageLabel(declaredLabels, currentPage)
    }, [pageLabels, declaredLabels, currentPage])

    const activePageMatchIndex = useMemo(
      () => activeMatchIndexForPage(globalMatches, globalMatchIndex, currentPage),
      [globalMatches, globalMatchIndex, currentPage],
    )

    // Apply search highlights as overlays whenever the page renders or the
    // active match changes.
    //
    // The dependency list is the fix for the flicker: this effect does not read
    // the match list -- applySearchHighlights re-derives matches from the text
    // layer -- it only needs to know which one is active. Depending on the array
    // re-ran it 62 times on a 600-page book as extraction progressed, and every
    // run clears all overlays before drawing the same highlights back.
    useEffect(() => {
      const textDiv = textLayerRef.current
      const overlayDiv = highlightOverlayRef.current
      if (!textDiv || !overlayDiv || textLayerVersion === 0) return
      if (!searchOpen || !searchQuery) {
        clearOverlays(overlayDiv, "data-search-highlight")
        lastHighlightRef.current = ""
        return
      }

      // Redrawing identical highlights is invisible work with a visible cost:
      // every application clears the overlay first, and that gap is the flicker.
      // React re-runs an effect whenever any dependency is merely recreated, so
      // the guard is on what was actually drawn.
      const signature = `${textLayerVersion}|${searchQuery}|${activePageMatchIndex}`
      if (lastHighlightRef.current === signature) return
      lastHighlightRef.current = signature

      applySearchHighlights(textDiv, overlayDiv, searchQuery, activePageMatchIndex)
    }, [textLayerVersion, searchOpen, searchQuery, activePageMatchIndex])

    function handleSearchNext() {
      if (globalMatches.length === 0) return
      const next = (globalMatchIndex + 1) % globalMatches.length
      setGlobalMatchIndex(next)
      const match = globalMatches[next]
      if (match.page !== currentPage) goToPage(match.page)
    }

    function handleSearchPrev() {
      if (globalMatches.length === 0) return
      const prev = (globalMatchIndex - 1 + globalMatches.length) % globalMatches.length
      setGlobalMatchIndex(prev)
      const match = globalMatches[prev]
      if (match.page !== currentPage) goToPage(match.page)
    }

    function closeSearch() {
      setSearchOpen(false)
      setSearchInput("")
      setSearchQuery("")
      setGlobalMatches([])
      setGlobalMatchIndex(-1)
    }

    // Keyboard navigation + Ctrl+F search shortcut
    useEffect(() => {
      function onKey(e: KeyboardEvent) {
        // Ctrl+F / Cmd+F opens search
        if ((e.ctrlKey || e.metaKey) && e.key === "f") {
          e.preventDefault()
          setSearchOpen(true)
          return
        }
        // Escape closes search (handled even from input)
        if (e.key === "Escape" && searchOpen) {
          closeSearch()
          return
        }
        if (
          e.target instanceof HTMLInputElement ||
          e.target instanceof HTMLTextAreaElement ||
          (e.target as HTMLElement).isContentEditable
        ) return
        if (e.key === "ArrowRight") goToPage(currentPage + 1)
        if (e.key === "ArrowLeft") goToPage(currentPage - 1)
      }
      window.addEventListener("keydown", onKey)
      return () => window.removeEventListener("keydown", onKey)
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [currentPage, totalPages, searchOpen])

    useEffect(() => {
      if (!zoomOpen) return
      const onDocPointerDown = (e: PointerEvent) => {
        const node = zoomPopoverRef.current
        if (node && !node.contains(e.target as Node)) setZoomOpen(false)
      }
      document.addEventListener("pointerdown", onDocPointerDown)
      return () => document.removeEventListener("pointerdown", onDocPointerDown)
    }, [zoomOpen])

    if (loadStatus === "loading") {
      return <Skeleton className="h-full w-full min-h-[600px]" />
    }

    if (loadStatus === "error") {
      return (
        <div className="flex items-center justify-center h-full min-h-[300px]">
          <p className="text-sm text-destructive">
            Could not load PDF file. The document may not be available on disk.
          </p>
        </div>
      )
    }

    const useOutline = shouldUseOutline(pdfOutline.length, tocSections.length)

    return (
      <div className="flex h-full">
        {toc.collapsed ? (
          <button
            type="button"
            onClick={toc.toggle}
            aria-label="Show contents"
            title="Show contents"
            className="flex h-full w-8 shrink-0 items-start justify-center border-r pt-3 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <PanelLeftOpen size={16} />
          </button>
        ) : (
        <div
          className="shrink-0 border-r overflow-y-auto p-2"
          style={{ width: toc.width }}
        >
          <div className="mb-2 flex items-center justify-between px-1">
            <p className="text-xs font-semibold uppercase text-muted-foreground">
              Contents
            </p>
            <button
              type="button"
              onClick={toc.toggle}
              aria-label="Hide contents"
              title="Hide contents"
              className="text-muted-foreground hover:text-foreground"
            >
              <PanelLeftClose size={14} />
            </button>
          </div>
          {useOutline ? (
            <ul className="space-y-0.5">
              {pdfOutline.map((entry, idx) => {
                const navigable = entry.page > 0
                // isActive: only for navigable entries. Find the next navigable
                // entry's page for the range upper bound.
                let isActive = false
                if (navigable) {
                  const nextNavigablePage = pdfOutline
                    .slice(idx + 1)
                    .find(e => e.page > 0)?.page ?? (totalPages + 1)
                  isActive = entry.page <= currentPage && currentPage < nextNavigablePage
                }
                return (
                  <li key={`outline-${idx}`}>
                    <button
                      className={`w-full text-left text-xs px-2 py-1 rounded truncate ${isActive
                          ? "bg-accent text-foreground font-medium"
                          : navigable
                            ? "text-muted-foreground hover:bg-accent"
                            : "text-muted-foreground/50 cursor-default"
                        }`}
                      style={{ paddingLeft: `${(entry.level - 1) * 8 + 8}px` }}
                      onClick={() => navigable && goToPage(entry.page)}
                      title={navigable ? `p.${entry.page} — ${entry.title}` : entry.title}
                      disabled={!navigable}
                    >
                      {entry.title}
                    </button>
                  </li>
                )
              })}
            </ul>
          ) : tocSections.length === 0 ? (
            <p className="text-xs text-muted-foreground px-1">No sections</p>
          ) : (() => {
            const hasPageNums = tocSections.some((s) => s.page_start > 0)
            // Normalize levels: shift so the minimum level present = 1.
            // This prevents all-L2 sections (from the backend parser) from
            // appearing indented with no L1 parents.
            const minLevel = Math.min(...tocSections.map(s => s.level))
            return (
              <ul className="space-y-0.5">
                {tocSections.map((sec, idx) => {
                  const displayLevel = sec.level - minLevel + 1
                  const targetPage = hasPageNums
                    ? sec.page_start
                    : Math.max(1, Math.round(((idx + 1) / tocSections.length) * totalPages))
                  const isActive =
                    targetPage <= currentPage &&
                    (hasPageNums
                      ? sec.page_end === 0 || currentPage <= sec.page_end
                      : idx === tocSections.length - 1 || Math.max(1, Math.round(((idx + 2) / tocSections.length) * totalPages)) > currentPage)
                  return (
                    <li key={sec.id}>
                      <button
                        className={`w-full text-left text-xs px-2 py-1 rounded hover:bg-accent truncate ${isActive ? "bg-accent text-foreground font-medium" : "text-muted-foreground"
                          }`}
                        style={{ paddingLeft: `${(displayLevel - 1) * 8 + 8}px` }}
                        onClick={() => goToPage(targetPage)}
                        title={hasPageNums ? `p.${targetPage} -- ${sec.heading}` : `~p.${targetPage} -- ${sec.heading}`}
                      >
                        {sec.heading}
                        {!hasPageNums && (
                          <span className="ml-1 text-muted-foreground opacity-60">~p.{targetPage}</span>
                        )}
                      </button>
                    </li>
                  )
                })}
              </ul>
            )
          })()}
        </div>
        )}
        {!toc.collapsed && (
          <PanelResizer
            onPointerDown={toc.onPointerDown}
            dragging={toc.dragging}
            label="Resize contents panel"
          />
        )}

        {/* Main viewer */}
        <div className="flex-1 flex flex-col overflow-hidden relative">
          {/* Search overlay */}
          {searchOpen && (
            <PdfSearchBar
              query={searchInput}
              onQueryChange={setSearchInput}
              matchLabel={
                searchQuery && extractedPageCount < totalPages
                  ? `${formatMatchCounts(globalMatches, globalMatchIndex, currentPage).label} (scanning...)`
                  : formatMatchCounts(globalMatches, globalMatchIndex, currentPage).label
              }
              onNext={handleSearchNext}
              onPrev={handleSearchPrev}
              onClose={closeSearch}
            />
          )}
          {/* Canvas scroll area */}
          <div ref={scrollAreaRef} className="flex-1 overflow-auto p-4">
            <div className="relative" style={{ width: "fit-content", marginInline: "auto" }}>
              {/* Canvas: pointer-events:none so the text layer receives all mouse events.
                  The filter lives on the canvas alone -- putting it on the parent would
                  invert the highlight/annotation overlays too. */}
              <canvas
                ref={canvasRef}
                className="shadow-md block"
                style={{ pointerEvents: "none", filter: canvasFilter }}
              />
              {/* Highlight overlay: absolutely-positioned colored divs between canvas and text layer.
                  z-index 5 sits above canvas (0) but below text layer (10), so text selection works
                  through the overlay while highlights are visible underneath. */}
              <div
                ref={highlightOverlayRef}
                style={{ position: "absolute", top: 0, left: 0, zIndex: 5, pointerEvents: "none" }}
              />
              {/* Official pdfjs textLayer -- supports drag-to-select, endOfContent marker,
                  and ::selection styling. Class "textLayer" matches pdf_viewer.css. */}
              <div ref={textLayerRef} className="textLayer" />
              {/* Official pdfjs annotationLayer -- handles links and form fields. */}
              <div ref={annotationLayerRef} className="annotationLayer" style={{ zIndex: 20, pointerEvents: "none" }} />
            </div>
            <canvas ref={nextCanvasRef} className="hidden" />
          </div>

          {/* Toolbar (moved to bottom) */}
          <div className="flex items-center gap-1 px-3 py-1.5 border-t bg-background flex-shrink-0">
            <button
              className="p-1 rounded hover:bg-accent disabled:opacity-40"
              onClick={() => goToPage(currentPage - 1)}
              disabled={currentPage <= 1}
              title="Previous page (←)"
              aria-label="Previous page"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <input
              type="number"
              // w-12 clipped a three-digit sheet: a 386-page book showed "34".
              className="w-16 text-center text-sm tabular-nums border rounded px-1 py-0.5"
              value={pageInput}
              min={1}
              max={totalPages}
              onChange={(e) => handlePageInputChange(e.target.value)}
              onBlur={commitPageInputNow}
              onKeyDown={(e) => { if (e.key === "Enter") commitPageInputNow() }}
              aria-label="Current page"
            />
            <span className="text-xs text-muted-foreground tabular-nums">/ {totalPages}</span>
            {printedLabel && (
              <span
                className="rounded bg-muted px-1.5 py-0.5 text-xs font-medium tabular-nums text-foreground/80"
                title="The number printed on this page. The box counts sheets in the file, which a book's separately numbered front matter makes differ."
              >
                p.{printedLabel}
              </span>
            )}
            <button
              className="p-1 rounded hover:bg-accent disabled:opacity-40"
              onClick={() => goToPage(currentPage + 1)}
              disabled={currentPage >= totalPages}
              title="Next page (→)"
              aria-label="Next page"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
            <button
              className="p-1 rounded hover:bg-accent ml-1"
              onClick={() => setSearchOpen((v) => !v)}
              title="Search in PDF (Ctrl+F)"
              aria-label="Search in PDF"
            >
              <Search className="h-4 w-4" />
            </button>
            <button
              className="p-1 rounded hover:bg-accent"
              onClick={() => setDarkPage((v) => !v)}
              title={darkPage ? "Show original page colors" : "Dark page (invert)"}
              aria-label="Toggle dark page"
              aria-pressed={darkPage}
            >
              {darkPage ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>
            {/* Zoom, as every PDF reader does it: the two common actions are one
                click each and always visible, and the percentage opens the
                presets. The old control was a popover slider capped at 200%,
                which could not even represent the 287% that auto-fit produces --
                so it showed a value it could not restore. */}
            <div className="ml-auto flex items-center gap-0.5" ref={zoomPopoverRef}>
              <button
                className="p-1 rounded hover:bg-accent disabled:opacity-40"
                onClick={() => setZoom(stepZoom(zoom, -1))}
                disabled={zoom <= ZOOM_STOPS[0]}
                title="Zoom out (Ctrl -)"
                aria-label="Zoom out"
              >
                <Minus className="h-4 w-4" />
              </button>
              <div className="relative">
                <button
                  className="min-w-[3.25rem] rounded px-1.5 py-1 text-xs tabular-nums hover:bg-accent"
                  onClick={() => setZoomOpen((v) => !v)}
                  title="Zoom presets"
                  aria-label="Zoom presets"
                  aria-expanded={zoomOpen}
                >
                  {Math.round(zoom * 100)}%
                </button>
                {zoomOpen && (
                  <div className="absolute right-0 bottom-full mb-2 z-30 min-w-[9rem] overflow-hidden rounded-md border bg-background py-1 shadow-md">
                    <button
                      className="block w-full px-3 py-1.5 text-left text-xs hover:bg-accent"
                      onClick={() => { fitToWidth(); setZoomOpen(false) }}
                    >
                      Fit width
                    </button>
                    <button
                      className="block w-full px-3 py-1.5 text-left text-xs hover:bg-accent"
                      onClick={() => { fitToPage(); setZoomOpen(false) }}
                    >
                      Fit page
                    </button>
                    <div className="my-1 border-t" />
                    {ZOOM_PRESETS.map((preset) => (
                      <button
                        key={preset}
                        className="block w-full px-3 py-1.5 text-left text-xs tabular-nums hover:bg-accent"
                        onClick={() => { setZoom(preset); setZoomOpen(false) }}
                      >
                        {Math.round(preset * 100)}%
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <button
                className="p-1 rounded hover:bg-accent disabled:opacity-40"
                onClick={() => setZoom(stepZoom(zoom, 1))}
                disabled={zoom >= ZOOM_STOPS[ZOOM_STOPS.length - 1]}
                title="Zoom in (Ctrl +)"
                aria-label="Zoom in"
              >
                <Plus className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  },
)
