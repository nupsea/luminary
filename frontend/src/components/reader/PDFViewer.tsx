import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react"
import * as pdfjsLib from "pdfjs-dist"
import { TextLayer } from "pdfjs-dist"
import type { PDFDocumentProxy, PDFPageProxy } from "pdfjs-dist"
import "pdfjs-dist/web/pdf_viewer.css"
import { API_BASE, PDFJS_WORKER_URL } from "@/lib/config"
import { Skeleton } from "@/components/ui/skeleton"
import type { SectionItem } from "./types"

// Set worker once at module load
pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER_URL

interface PDFViewerProps {
  documentId: string
  sections: SectionItem[]
  initialPage?: number  // S148: navigate to this page after PDF loads (from citation deep-link)
}

export interface PDFViewerHandle {
  goToPage: (n: number) => void
}

type LoadStatus = "loading" | "error" | "ready"

export const PDFViewer = forwardRef<PDFViewerHandle, PDFViewerProps>(
  function PDFViewer({ documentId, sections, initialPage }, ref) {
    const [pdfDoc, setPdfDoc] = useState<PDFDocumentProxy | null>(null)
    const [currentPage, setCurrentPage] = useState(1)
    const [totalPages, setTotalPages] = useState(0)
    const [zoom, setZoom] = useState(1.0)
    const [loadStatus, setLoadStatus] = useState<LoadStatus>("loading")
    const [pageInput, setPageInput] = useState("1")

    const canvasRef = useRef<HTMLCanvasElement>(null)
    const textLayerRef = useRef<HTMLDivElement>(null)
    const nextCanvasRef = useRef<HTMLCanvasElement>(null)
    const scrollAreaRef = useRef<HTMLDivElement>(null)

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
        })
        .catch(() => {
          if (!cancelled) setLoadStatus("error")
        })

      return () => {
        cancelled = true
        task.destroy().catch(() => undefined)
      }
    }, [documentId])

    // S148: navigate to initialPage once the PDF is loaded
    useEffect(() => {
      if (!initialPage || loadStatus !== "ready" || !totalPages) return
      if (initialPage >= 1 && initialPage <= totalPages) {
        setCurrentPage(initialPage)
        setPageInput(String(initialPage))
      }
    // Only fire once after load
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [loadStatus, totalPages])

    // Render the current page + pre-render next for fast navigation
    useEffect(() => {
      if (!pdfDoc || loadStatus !== "ready") return

      let cancelled = false
      let activeTextLayer: TextLayer | null = null

      async function renderPage(
        pageNum: number,
        canvas: HTMLCanvasElement | null,
        textLayerDiv: HTMLDivElement | null,
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

          await page.render({ canvasContext: ctx, viewport }).promise
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
          }
        } finally {
          page?.cleanup()
        }
      }

      void renderPage(currentPage, canvasRef.current, textLayerRef.current)
      if (currentPage < totalPages) {
        void renderPage(currentPage + 1, nextCanvasRef.current, null)
      }

      return () => {
        cancelled = true
        activeTextLayer?.cancel()
      }
    }, [pdfDoc, currentPage, zoom, totalPages, loadStatus])

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

    return (
      <div className="flex h-full">
        {/* TOC panel */}
        <div className="w-40 flex-shrink-0 border-r overflow-y-auto p-2">
          <p className="text-xs font-semibold uppercase text-muted-foreground mb-2 px-1">
            Contents
          </p>
          {sections.length === 0 ? (
            <p className="text-xs text-muted-foreground px-1">No sections</p>
          ) : (() => {
            const hasPageNums = sections.some((s) => s.page_start > 0)
            return (
              <ul className="space-y-0.5">
                {sections.map((sec, idx) => {
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
                        style={{ paddingLeft: `${(sec.level - 1) * 8 + 8}px` }}
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
          {/* Toolbar */}
          <div className="flex items-center gap-2 px-3 py-2 border-b bg-background flex-shrink-0">
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

          {/* Canvas scroll area */}
          <div ref={scrollAreaRef} className="flex-1 overflow-auto p-4">
            <div className="relative" style={{ width: "fit-content", marginInline: "auto" }}>
              {/* Canvas: pointer-events:none so the text layer receives all mouse events */}
              <canvas ref={canvasRef} className="shadow-md block" style={{ pointerEvents: "none" }} />
              {/* Official pdfjs textLayer -- supports drag-to-select, endOfContent marker,
                  and ::selection styling. Class "textLayer" matches pdf_viewer.css. */}
              <div ref={textLayerRef} className="textLayer" />
            </div>
            <canvas ref={nextCanvasRef} className="hidden" />
          </div>
        </div>
      </div>
    )
  },
)
