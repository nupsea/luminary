import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react"
import * as pdfjsLib from "pdfjs-dist"
import { AnnotationLayer, TextLayer } from "pdfjs-dist"
import type { PDFDocumentProxy, PDFPageProxy } from "pdfjs-dist"
import "pdfjs-dist/web/pdf_viewer.css"
import { API_BASE, PDFJS_WORKER_URL } from "@/lib/config"
import { Skeleton } from "@/components/ui/skeleton"
import type { AnnotationItem, SectionItem } from "./types"
import {
  type OutlineEntry,
  buildFontTOC,
  flattenOutline,
  resolveOutline,
  shouldUseOutline,
} from "./pdfTocUtils"

// Set worker once at module load
pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER_URL

/** Apply highlight overlays to PDF text layer spans by matching annotation selected_text. */
function applyPdfHighlights(
  textLayerDiv: HTMLDivElement,
  annotations: AnnotationItem[],
  currentPage: number,
  sections: SectionItem[],
) {
  // Clear any previous highlight marks
  textLayerDiv.querySelectorAll("mark[data-pdf-highlight]").forEach((m) => {
    const parent = m.parentNode
    if (parent) {
      parent.replaceChild(document.createTextNode(m.textContent ?? ""), m)
      parent.normalize()
    }
  })
  // Reset background on previously highlighted spans
  textLayerDiv.querySelectorAll("span[data-hl-original]").forEach((span) => {
    ;(span as HTMLElement).style.backgroundColor = ""
    span.removeAttribute("data-hl-original")
  })

  if (annotations.length === 0) return

  // Filter annotations relevant to current page:
  // 1. By explicit page_number field
  // 2. By section page range
  // 3. Fallback: try matching any annotation's text against page content
  const pageAnnotations = annotations.filter((ann) => {
    if (ann.page_number != null) return ann.page_number === currentPage
    const sec = sections.find((s) => s.id === ann.section_id)
    if (sec) {
      const start = sec.page_start || 1
      const end = sec.page_end || start
      return currentPage >= start && currentPage <= end
    }
    return true // fallback: try matching
  })

  if (pageAnnotations.length === 0) return

  // Collect text spans
  const spans = Array.from(textLayerDiv.querySelectorAll("span")) as HTMLSpanElement[]
  if (spans.length === 0) return

  // Build concatenated text with space separators between spans.
  // Browser selection toString() inserts spaces between spans, so we must match
  // with the same spacing.
  const parts: { span: HTMLSpanElement; start: number; end: number }[] = []
  let offset = 0
  for (let i = 0; i < spans.length; i++) {
    if (i > 0) offset += 1 // space separator
    const text = spans[i].textContent ?? ""
    parts.push({ span: spans[i], start: offset, end: offset + text.length })
    offset += text.length
  }
  const fullText = spans.map((s) => s.textContent ?? "").join(" ")

  for (const ann of pageAnnotations) {
    // Try exact match first, then normalized whitespace match
    let idx = fullText.indexOf(ann.selected_text)
    let searchText = ann.selected_text
    if (idx < 0) {
      // Normalize both: collapse whitespace runs to single space
      const normFull = fullText.replace(/\s+/g, " ")
      const normSearch = ann.selected_text.replace(/\s+/g, " ")
      const normIdx = normFull.indexOf(normSearch)
      if (normIdx < 0) continue
      // Map normalized index back to fullText offset
      // Walk fullText counting chars while tracking normalized position
      let fi = 0
      let ni = 0
      while (ni < normIdx && fi < fullText.length) {
        if (/\s/.test(fullText[fi])) {
          // Skip extra whitespace chars that got collapsed
          fi++
          if (ni < normFull.length && /\s/.test(normFull[ni])) ni++
          while (fi < fullText.length && /\s/.test(fullText[fi])) fi++
        } else {
          fi++
          ni++
        }
      }
      idx = fi
      // Use the length in fullText space
      let endFi = fi
      let endNi = ni
      while (endNi < normIdx + normSearch.length && endFi < fullText.length) {
        if (/\s/.test(fullText[endFi])) {
          endFi++
          if (endNi < normFull.length && /\s/.test(normFull[endNi])) endNi++
          while (endFi < fullText.length && /\s/.test(fullText[endFi])) endFi++
        } else {
          endFi++
          endNi++
        }
      }
      searchText = fullText.slice(idx, endFi)
    }

    const matchEnd = idx + searchText.length
    const bgColor = PDF_HIGHLIGHT_COLORS[ann.color] ?? PDF_HIGHLIGHT_COLORS.yellow

    for (const part of parts) {
      if (part.end <= idx || part.start >= matchEnd) continue

      // Fully inside
      if (part.start >= idx && part.end <= matchEnd) {
        part.span.style.backgroundColor = bgColor
        part.span.setAttribute("data-hl-original", "1")
        continue
      }

      // Partially inside -- wrap matching portion in <mark>
      const spanText = part.span.textContent ?? ""
      const localStart = Math.max(0, idx - part.start)
      const localEnd = Math.min(spanText.length, matchEnd - part.start)

      const before = spanText.slice(0, localStart)
      const matched = spanText.slice(localStart, localEnd)
      const after = spanText.slice(localEnd)

      const frag = document.createDocumentFragment()
      if (before) frag.appendChild(document.createTextNode(before))
      const mark = document.createElement("mark")
      mark.setAttribute("data-pdf-highlight", "1")
      mark.style.backgroundColor = bgColor
      mark.style.borderRadius = "2px"
      mark.textContent = matched
      frag.appendChild(mark)
      if (after) frag.appendChild(document.createTextNode(after))

      part.span.replaceChildren(frag)
    }
  }
}

const PDF_HIGHLIGHT_COLORS: Record<string, string> = {
  yellow: "rgba(254, 240, 138, 0.5)",
  green: "rgba(187, 247, 208, 0.5)",
  blue: "rgba(191, 219, 254, 0.5)",
  pink: "rgba(251, 207, 232, 0.5)",
}

interface PDFViewerProps {
  documentId: string
  sections: SectionItem[]
  initialPage?: number  // S148: navigate to this page after PDF loads (from citation deep-link)
  annotations?: AnnotationItem[]
  highlightsVisible?: boolean
  onPageChange?: (page: number) => void
}

export interface PDFViewerHandle {
  goToPage: (n: number) => void
}

type LoadStatus = "loading" | "error" | "ready"

export const PDFViewer = forwardRef<PDFViewerHandle, PDFViewerProps>(
  function PDFViewer({ documentId, sections, initialPage, annotations = [], highlightsVisible = true, onPageChange }, ref) {
    const [pdfDoc, setPdfDoc] = useState<PDFDocumentProxy | null>(null)
    const [currentPage, setCurrentPage] = useState(1)
    const [totalPages, setTotalPages] = useState(0)
    const [zoom, setZoom] = useState(1.0)
    const [loadStatus, setLoadStatus] = useState<LoadStatus>("loading")
    const [pageInput, setPageInput] = useState("1")

    const canvasRef = useRef<HTMLCanvasElement>(null)
    const textLayerRef = useRef<HTMLDivElement>(null)
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

      const task = pdfjsLib.getDocument({
        url: `${API_BASE}/documents/${documentId}/file`,
      })

      task.promise
        .then(async (doc) => {
          if (cancelled) return
          setPdfDoc(doc)
          setTotalPages(doc.numPages)
          setLoadStatus("ready")

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

          // ── TOC source determination ─────────────────────────────────────
          // Rule 1 — Native PDF bookmarks (always preferred when present).
          //   Standard PDFs embed an authored outline; use every entry in it.
          //   Entries whose page cannot be resolved are kept as static labels
          //   so the full TOC structure is always visible.
          //   Sort navigable entries (page > 0) by page; unresolvable entries
          //   follow in their original declaration order.
          // Rule 2 — Font-size scanning (only when no native outline exists).
          //   PDFs without bookmarks (e.g. scanned or minimal exports) fall back
          //   to scanning heading-sized text across all pages.
          try {
            const rawOutline = await doc.getOutline()
            if (rawOutline && rawOutline.length > 0 && !cancelled) {
              // Rule 1: native outline present — resolve and use all entries
              const resolved = await resolveOutline(doc, rawOutline, 1)
              if (!cancelled) {
                const flat = flattenOutline(resolved)
                // Navigable entries sorted by page; unresolved entries keep
                // their original DFS (reading) order appended after.
                const navigable = flat.filter(e => e.page > 0).sort((a, b) => a.page - b.page)
                const unresolved = flat.filter(e => e.page === 0)
                setPdfOutline([...navigable, ...unresolved])
              }
            } else if (!cancelled) {
              // Rule 2: no native outline — scan font sizes
              const fontToc = await buildFontTOC(doc, () => cancelled)
              if (!cancelled && fontToc.length > 0) setPdfOutline(fontToc)
            }
          } catch {
            // non-fatal; TOC panel falls back to backend sections
          }
        })
        .catch(() => {
          if (!cancelled) setLoadStatus("error")
        })

      return () => {
        cancelled = true
        task.destroy().catch(() => undefined)
      }
    }, [documentId])

    // S148: navigate to initialPage once the PDF is loaded or when initialPage changes
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
          canvas.width = viewport.width
          canvas.height = viewport.height

          const ctx = canvas.getContext("2d")
          if (!ctx || cancelled) return

          const renderTask = page.render({ canvasContext: ctx, viewport })
          activeRenderTasks.push(renderTask)
          try {
            await renderTask.promise
          } catch (e: unknown) {
            // RenderingCancelledException is expected when the effect is cleaned up
            if (e instanceof Error && e.name === "RenderingCancelledException") return
            throw e
          }
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
            // Set explicit dimensions as fallback
            textLayerDiv.style.width = `${viewport.width}px`
            textLayerDiv.style.height = `${viewport.height}px`

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
              // Apply highlights immediately after text layer is ready
              if (highlightsVisibleRef.current && annotationsRef.current.length > 0) {
                applyPdfHighlights(textLayerDiv, annotationsRef.current, pageNum, sections)
              }
              setTextLayerVersion((v) => v + 1)
            }
          }

          // Annotation Layer -- handles links (external browser links and internal page jumps)
          if (annotationLayerDiv && !cancelled) {
            console.log(`[PDFViewer] rendering annotations for page ${pageNum}`, { annotationLayerDiv })
            annotationLayerDiv.replaceChildren()
            annotationLayerDiv.style.width = `${viewport.width}px`
            annotationLayerDiv.style.height = `${viewport.height}px`

            try {
              const annotationsData = await page.getAnnotations()
              console.log(`[PDFViewer] found ${annotationsData.length} annotations for page ${pageNum}`)
              if (cancelled) return

              // Minimal link service to handle "goToPage" for internal links (Rules 1/2)
              // and "BLANK" target for external browser links (e.g. GitHub repos).
              const linkService = {
                externalLinkTarget: 2, // BLANK
                externalLinkRel: "noopener noreferrer nofollow",
                externalLinkEnabled: true,
                getDestinationHash: () => "#",
                getAnchorUrl: () => "#",
                setHash: () => {},
                executeNamedAction: () => {},
                cachePageRef: () => {},
                addLinkAttributes(link: HTMLAnchorElement, url: string, newWindow: boolean) {
                  if (url) link.href = url
                  if (newWindow) {
                    link.target = "_blank"
                    link.rel = "noopener noreferrer nofollow"
                  }
                },
                async navigateTo(dest: unknown) {
                  console.log("[PDFViewer] navigateTo", dest)
                  if (!pdfDoc) return
                  let pageIdx: number | null = null
                  if (typeof dest === "string") {
                    const resolved = await pdfDoc.getDestination(dest)
                    if (resolved && Array.isArray(resolved)) {
                      pageIdx = await pdfDoc.getPageIndex(resolved[0])
                    }
                  } else if (Array.isArray(dest)) {
                    pageIdx = await pdfDoc.getPageIndex(dest[0])
                  }
                  if (pageIdx !== null) {
                    console.log(`[PDFViewer] jumping to page ${pageIdx + 1}`)
                    goToPage(pageIdx + 1)
                  }
                },
              }

              const al = new AnnotationLayer({
                div: annotationLayerDiv,
                accessibilityManager: null,
                annotationCanvasMap: null,
                annotationEditorUIManager: null,
                page,
                viewport: viewport.clone({ dontFlip: true }),
              } as any) // eslint-disable-line @typescript-eslint/no-explicit-any

              await al.render({
                annotations: annotationsData,
                viewport: viewport.clone({ dontFlip: true }),
                linkService: linkService as any, // eslint-disable-line @typescript-eslint/no-explicit-any
                div: annotationLayerDiv,
                intent: "display",
              } as any) // eslint-disable-line @typescript-eslint/no-explicit-any
              console.log(`[PDFViewer] annotation layer rendered for page ${pageNum}`)
            } catch (err) {
              console.error(`[PDFViewer] failed to render annotations for page ${pageNum}`, err)
            }
          }
        } finally {
          page?.cleanup()
        }
      }

      console.log(`[PDFViewer] triggering renderPage for page ${currentPage}`)
      void renderPage(currentPage, canvasRef.current, textLayerRef.current, annotationLayerRef.current)
      if (currentPage < totalPages) {
        void renderPage(currentPage + 1, nextCanvasRef.current, null, null)
      }

      return () => {
        cancelled = true
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

    // Apply inline highlights on the text layer after it finishes rendering
    useEffect(() => {
      const textDiv = textLayerRef.current
      if (!textDiv || textLayerVersion === 0) return
      if (!highlightsVisible || annotations.length === 0) {
        // Clear any existing highlights when toggled off
        textDiv.querySelectorAll("mark[data-pdf-highlight]").forEach((m) => {
          const parent = m.parentNode
          if (parent) {
            parent.replaceChild(document.createTextNode(m.textContent ?? ""), m)
            parent.normalize()
          }
        })
        textDiv.querySelectorAll("span[data-hl-original]").forEach((span) => {
          ;(span as HTMLElement).style.backgroundColor = ""
          span.removeAttribute("data-hl-original")
        })
        return
      }
      applyPdfHighlights(textDiv, annotations, currentPage, sections)
    }, [textLayerVersion, annotations, highlightsVisible, currentPage, sections])

    function goToPage(n: number) {
      const clamped = Math.max(1, Math.min(n, totalPages))
      setCurrentPage(clamped)
      setPageInput(String(clamped))
    }

    function commitPageInput() {
      const n = parseInt(pageInput, 10)
      if (!isNaN(n)) goToPage(n)
    }

    // Keyboard navigation
    useEffect(() => {
      function onKey(e: KeyboardEvent) {
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
    }, [currentPage, totalPages])

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

    const useOutline = shouldUseOutline(pdfOutline.length, sections.length)

    return (
      <div className="flex h-full">
        {/* TOC panel -- prefer whichever source has more entries for granular navigation */}
        <div className="w-56 flex-shrink-0 border-r overflow-y-auto p-2">
          <p className="text-xs font-semibold uppercase text-muted-foreground mb-2 px-1">
            Contents
          </p>
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
                      className={`w-full text-left text-xs px-2 py-1 rounded truncate ${
                        isActive
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
          ) : sections.length === 0 ? (
            <p className="text-xs text-muted-foreground px-1">No sections</p>
          ) : (() => {
            const hasPageNums = sections.some((s) => s.page_start > 0)
            // Normalize levels: shift so the minimum level present = 1.
            // This prevents all-L2 sections (from the backend parser) from
            // appearing indented with no L1 parents.
            const minLevel = Math.min(...sections.map(s => s.level))
            return (
              <ul className="space-y-0.5">
                {sections.map((sec, idx) => {
                  const displayLevel = sec.level - minLevel + 1
                  const targetPage = hasPageNums
                    ? sec.page_start
                    : Math.max(1, Math.round(((idx + 1) / sections.length) * totalPages))
                  const isActive =
                    targetPage <= currentPage &&
                    (hasPageNums
                      ? sec.page_end === 0 || currentPage <= sec.page_end
                      : idx === sections.length - 1 || Math.max(1, Math.round(((idx + 2) / sections.length) * totalPages)) > currentPage)
                  return (
                    <li key={sec.id}>
                      <button
                        className={`w-full text-left text-xs px-2 py-1 rounded hover:bg-accent truncate ${
                          isActive ? "bg-accent text-foreground font-medium" : "text-muted-foreground"
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

        {/* Main viewer */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Canvas scroll area */}
          <div ref={scrollAreaRef} className="flex-1 overflow-auto p-4">
            <div className="relative" style={{ width: "fit-content", marginInline: "auto" }}>
              {/* Canvas: pointer-events:none so the text layer receives all mouse events */}
              <canvas ref={canvasRef} className="shadow-md block" style={{ pointerEvents: "none" }} />
              {/* Official pdfjs textLayer -- supports drag-to-select, endOfContent marker,
                  and ::selection styling. Class "textLayer" matches pdf_viewer.css. */}
              <div ref={textLayerRef} className="textLayer" />
              {/* Official pdfjs annotationLayer -- handles links and form fields. */}
              <div ref={annotationLayerRef} className="annotationLayer" />
            </div>
            <canvas ref={nextCanvasRef} className="hidden" />
          </div>

          {/* Toolbar (moved to bottom) */}
          <div className="flex items-center gap-2 px-3 py-2 border-t bg-background flex-shrink-0">
            <button
              className="px-2 py-1 text-sm border rounded hover:bg-accent disabled:opacity-40"
              onClick={() => goToPage(currentPage - 1)}
              disabled={currentPage <= 1}
            >
              Prev
            </button>
            <input
              type="number"
              className="w-14 text-center text-sm border rounded px-1 py-1"
              value={pageInput}
              min={1}
              max={totalPages}
              onChange={(e) => setPageInput(e.target.value)}
              onBlur={commitPageInput}
              onKeyDown={(e) => { if (e.key === "Enter") commitPageInput() }}
              aria-label="Current page"
            />
            <span className="text-sm text-muted-foreground">/ {totalPages}</span>
            <button
              className="px-2 py-1 text-sm border rounded hover:bg-accent disabled:opacity-40"
              onClick={() => goToPage(currentPage + 1)}
              disabled={currentPage >= totalPages}
            >
              Next
            </button>
            <div className="flex items-center gap-1 ml-auto">
              <span className="text-xs text-muted-foreground">Zoom</span>
              <input
                type="range"
                min={50}
                max={200}
                step={10}
                value={Math.round(zoom * 100)}
                onChange={(e) => setZoom(parseInt(e.target.value, 10) / 100)}
                className="w-24"
                aria-label="Zoom level"
              />
              <span className="text-xs w-10">{Math.round(zoom * 100)}%</span>
            </div>
          </div>
        </div>
      </div>
    )
  },
)
