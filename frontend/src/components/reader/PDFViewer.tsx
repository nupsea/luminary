import { useEffect, useRef, useState } from "react"
import * as pdfjsLib from "pdfjs-dist"
import type { PDFDocumentProxy, PDFPageProxy } from "pdfjs-dist"
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

type LoadStatus = "loading" | "error" | "ready"

export function PDFViewer({ documentId, sections, initialPage }: PDFViewerProps) {
  const [pdfDoc, setPdfDoc] = useState<PDFDocumentProxy | null>(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [totalPages, setTotalPages] = useState(0)
  const [zoom, setZoom] = useState(1.0) // 1.0 = 100%
  const [loadStatus, setLoadStatus] = useState<LoadStatus>("loading")
  const [pageInput, setPageInput] = useState("1")

  const canvasRef = useRef<HTMLCanvasElement>(null)
  const textLayerRef = useRef<HTMLDivElement>(null)
  const nextCanvasRef = useRef<HTMLCanvasElement>(null)

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
      .then((doc) => {
        if (cancelled) return
        setPdfDoc(doc)
        setTotalPages(doc.numPages)
        setLoadStatus("ready")
      })
      .catch(() => {
        if (!cancelled) setLoadStatus("error")
      })

    return () => {
      cancelled = true
      task.destroy().catch(() => undefined)
    }
  }, [documentId])

  // S148: navigate to initialPage once the PDF is loaded (from citation deep-link)
  useEffect(() => {
    if (!initialPage || loadStatus !== "ready" || !totalPages) return
    if (initialPage >= 1 && initialPage <= totalPages) {
      setCurrentPage(initialPage)
      setPageInput(String(initialPage))
    }
  // Only fire once after load — intentionally exclude initialPage from deps to avoid re-triggering
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadStatus, totalPages])

  // Render the current page (and pre-render current+1 for fast navigation)
  useEffect(() => {
    if (!pdfDoc || loadStatus !== "ready") return

    let cancelled = false

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

        // Text layer for selection (required by S147)
        if (textLayerDiv) {
          textLayerDiv.style.width = `${viewport.width}px`
          textLayerDiv.style.height = `${viewport.height}px`
          // Clear previous text layer content
          textLayerDiv.replaceChildren()

          const textContent = await page.getTextContent()
          if (!cancelled) {
            const tl = new pdfjsLib.TextLayer({
              textContentSource: textContent,
              container: textLayerDiv,
              viewport,
            })
            await tl.render()
          }
        }
      } finally {
        page?.cleanup()
      }
    }

    void renderPage(currentPage, canvasRef.current, textLayerRef.current)
    // Pre-render next page for fast forward navigation (no text layer needed)
    if (currentPage < totalPages) {
      void renderPage(currentPage + 1, nextCanvasRef.current, null)
    }

    return () => {
      cancelled = true
    }
  }, [pdfDoc, currentPage, zoom, totalPages, loadStatus])

  function goToPage(n: number) {
    const clamped = Math.max(1, Math.min(n, totalPages))
    setCurrentPage(clamped)
    setPageInput(String(clamped))
  }

  function handlePrev() {
    goToPage(currentPage - 1)
  }

  function handleNext() {
    goToPage(currentPage + 1)
  }

  function handlePageInputCommit() {
    const n = parseInt(pageInput, 10)
    if (!isNaN(n)) goToPage(n)
  }

  // Keyboard navigation: skip if focus is on an input element
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        (e.target as HTMLElement).isContentEditable
      ) {
        return
      }
      if (e.key === "ArrowRight") handleNext()
      if (e.key === "ArrowLeft") handlePrev()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
    // handleNext/handlePrev close over currentPage/totalPages which are already deps;
    // omitting the inline functions avoids infinite re-renders from re-creating them.
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
      <div className="w-56 flex-shrink-0 border-r overflow-y-auto p-2">
        <p className="text-xs font-semibold uppercase text-muted-foreground mb-2 px-1">
          Contents
        </p>
        {sections.length === 0 ? (
          <p className="text-xs text-muted-foreground px-1">No sections</p>
        ) : (
          <ul className="space-y-0.5">
            {sections.map((sec) => (
              <li key={sec.id}>
                <button
                  className="w-full text-left text-xs px-2 py-1 rounded hover:bg-accent truncate"
                  style={{ paddingLeft: `${(sec.level - 1) * 8 + 8}px` }}
                  onClick={() => goToPage(sec.page_start || 1)}
                  title={sec.heading}
                >
                  {sec.heading}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Main viewer */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Toolbar */}
        <div className="flex items-center gap-2 px-3 py-2 border-b bg-background flex-shrink-0">
          <button
            className="px-2 py-1 text-sm border rounded hover:bg-accent disabled:opacity-40"
            onClick={handlePrev}
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
            onBlur={handlePageInputCommit}
            onKeyDown={(e) => {
              if (e.key === "Enter") handlePageInputCommit()
            }}
            aria-label="Current page"
          />
          <span className="text-sm text-muted-foreground">/ {totalPages}</span>
          <button
            className="px-2 py-1 text-sm border rounded hover:bg-accent disabled:opacity-40"
            onClick={handleNext}
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

        {/* Canvas area */}
        <div className="flex-1 overflow-auto p-4">
          {/* Visible page */}
          <div className="relative inline-block">
            <canvas ref={canvasRef} className="shadow-md block" />
            <div
              ref={textLayerRef}
              className="absolute top-0 left-0 overflow-hidden"
              style={{ opacity: 0.25, lineHeight: 1.0, pointerEvents: "auto" }}
            />
          </div>
          {/* Pre-rendered next page (hidden, kept in DOM for fast access) */}
          <canvas ref={nextCanvasRef} className="hidden" />
        </div>
      </div>
    </div>
  )
}
