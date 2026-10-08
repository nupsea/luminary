import { memo, useEffect, useRef, useState } from "react"
import { AnnotationLayer, TextLayer } from "pdfjs-dist"
import type { PDFDocumentProxy, RenderTask } from "pdfjs-dist"
import { CITATION_OVERLAY_ATTR } from "@/lib/citation"
import type { AnnotationItem, SectionItem } from "./types"
import { createLinkService } from "./pdfLinkService"
import { clearOverlays } from "./pdfHighlightOverlay"
import { applyCitationHighlight, applyPdfHighlights, applySearchHighlights } from "./pdfPageHighlights"

/** What has already been scrolled to, shared by every page so each target scrolls once. */
export interface ScrollMarks {
  citation: boolean
  searchKey: string
}

interface PdfPageProps {
  pdfDoc: PDFDocumentProxy
  pageNum: number
  zoom: number
  top: number
  width: number
  height: number
  /** Near the viewport: holds a canvas and text layer. Off, it is an empty placeholder. */
  live: boolean
  canvasFilter: string | undefined
  annotations: AnnotationItem[]
  sections: SectionItem[]
  searchQuery: string
  /** Index of the active match among this page's matches, or -1. */
  activeMatch: number
  /** Changes whenever the active match does, so a new one is scrolled to. */
  searchKey: string
  citationWords: string[]
  scrollMarks: React.RefObject<ScrollMarks>
  goToPage: (n: number) => void
  onNaturalSize: (pageNum: number, width: number, height: number) => void
}

const ANNOTATION_STYLE = `
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

function ensureAnnotationStyle() {
  if (document.getElementById("pdf-annotation-style")) return
  const style = document.createElement("style")
  style.id = "pdf-annotation-style"
  style.textContent = ANNOTATION_STYLE
  document.head.appendChild(style)
}

function sizeLayer(div: HTMLDivElement, width: number, height: number, scale: number, zIndex: number) {
  div.style.position = "absolute"
  div.style.top = "0"
  div.style.left = "0"
  div.style.width = `${width}px`
  div.style.height = `${height}px`
  div.style.zIndex = String(zIndex)
  div.style.setProperty("--scale-factor", String(scale))
}

/** One page of the continuous view: canvas, highlight overlay, text layer and link layer. */
export const PdfPage = memo(function PdfPage({
  pdfDoc, pageNum, zoom, top, width, height, live, canvasFilter,
  annotations, sections, searchQuery, activeMatch, searchKey, citationWords,
  scrollMarks, goToPage, onNaturalSize,
}: PdfPageProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const overlayRef = useRef<HTMLDivElement>(null)
  const textLayerRef = useRef<HTMLDivElement>(null)
  const annotationLayerRef = useRef<HTMLDivElement>(null)
  // Bumped once the text layer is rendered, so the highlights can be located in it.
  const [textVersion, setTextVersion] = useState(0)

  useEffect(() => {
    const canvas = canvasRef.current
    const textDiv = textLayerRef.current
    const overlay = overlayRef.current
    const linkDiv = annotationLayerRef.current
    if (!canvas || !textDiv || !overlay || !linkDiv) return
    if (!live) {
      // Release the bitmap: a long book would otherwise hold one per page visited.
      canvas.width = 0
      canvas.height = 0
      textDiv.replaceChildren()
      overlay.replaceChildren()
      linkDiv.replaceChildren()
      return
    }

    let cancelled = false
    let renderTask: RenderTask | null = null
    let textLayer: TextLayer | null = null

    void (async () => {
      const page = await pdfDoc.getPage(pageNum)
      try {
        if (cancelled) return
        const natural = page.getViewport({ scale: 1 })
        onNaturalSize(pageNum, natural.width, natural.height)
        const viewport = page.getViewport({ scale: zoom })

        // The backing store is sized in device pixels and scaled back down in
        // CSS, or a retina display upscales a 1x bitmap and every glyph is soft.
        const outputScale = window.devicePixelRatio || 1
        canvas.width = Math.floor(viewport.width * outputScale)
        canvas.height = Math.floor(viewport.height * outputScale)
        canvas.style.width = `${Math.floor(viewport.width)}px`
        canvas.style.height = `${Math.floor(viewport.height)}px`
        const ctx = canvas.getContext("2d")
        if (!ctx) return

        renderTask = page.render({
          canvasContext: ctx,
          viewport,
          transform: outputScale === 1 ? undefined : [outputScale, 0, 0, outputScale, 0, 0],
        })
        try {
          await renderTask.promise
        } catch (e: unknown) {
          if (e instanceof Error && e.name === "RenderingCancelledException") return
          throw e
        }
        if (cancelled) return

        textDiv.replaceChildren()
        sizeLayer(textDiv, viewport.width, viewport.height, viewport.scale, 10)
        textLayer = new TextLayer({ textContentSource: await page.getTextContent(), container: textDiv, viewport })
        await textLayer.render()
        if (cancelled) return
        overlay.style.width = `${viewport.width}px`
        overlay.style.height = `${viewport.height}px`
        overlay.replaceChildren()
        setTextVersion((v) => v + 1)

        linkDiv.replaceChildren()
        sizeLayer(linkDiv, viewport.width, viewport.height, viewport.scale, 20)
        ensureAnnotationStyle()
        const annotationsData = await page.getAnnotations()
        if (cancelled) return
        const al = new AnnotationLayer({
          div: linkDiv,
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
          linkService: createLinkService(pdfDoc, goToPage),
          intent: "display",
        } as any)
      } finally {
        page.cleanup()
      }
    })().catch((err) => {
      if (!cancelled) console.warn(`[PDFViewer] page ${pageNum} failed to render`, err)
    })

    return () => {
      cancelled = true
      renderTask?.cancel()
      textLayer?.cancel()
    }
  }, [pdfDoc, pageNum, zoom, live, goToPage, onNaturalSize])

  useEffect(() => {
    const textDiv = textLayerRef.current
    const overlay = overlayRef.current
    if (!textDiv || !overlay || !live || textVersion === 0) return
    applyPdfHighlights(textDiv, overlay, annotations, pageNum, sections)
  }, [textVersion, live, annotations, sections, pageNum])

  useEffect(() => {
    const textDiv = textLayerRef.current
    const overlay = overlayRef.current
    if (!textDiv || !overlay || !live || textVersion === 0) return
    if (!searchQuery) {
      clearOverlays(overlay, "data-search-highlight")
      return
    }
    const active = applySearchHighlights(textDiv, overlay, searchQuery, activeMatch)
    if (active && scrollMarks.current.searchKey !== searchKey) {
      scrollMarks.current.searchKey = searchKey
      active.scrollIntoView({ behavior: "smooth", block: "center" })
    }
  }, [textVersion, live, searchQuery, activeMatch, searchKey, scrollMarks])

  // A chunk can straddle a page break, and the sheet a citation carries is the one
  // its first line fell on, so every rendered page looks for the passage.
  useEffect(() => {
    const textDiv = textLayerRef.current
    const overlay = overlayRef.current
    if (!textDiv || !overlay || !live || textVersion === 0) return
    const drawn = applyCitationHighlight(textDiv, overlay, citationWords)
    if (drawn && !scrollMarks.current.citation) {
      scrollMarks.current.citation = true
      overlay.querySelector(`[${CITATION_OVERLAY_ATTR}]`)?.scrollIntoView({ behavior: "smooth", block: "center" })
    }
  }, [textVersion, live, citationWords, scrollMarks])

  return (
    <div
      data-pdf-page={pageNum}
      className="absolute inset-x-0 mx-auto bg-muted/40 shadow-md"
      style={{ top, width, height }}
    >
      {/* pointer-events:none so the text layer receives all mouse events. The filter
          sits on the canvas alone, or it would invert the highlight overlays too. */}
      <canvas ref={canvasRef} className="block" style={{ pointerEvents: "none", filter: canvasFilter }} />
      {/* Between the canvas and the text layer: highlights show, selection works through them. */}
      <div ref={overlayRef} style={{ position: "absolute", top: 0, left: 0, zIndex: 5, pointerEvents: "none" }} />
      <div ref={textLayerRef} className="textLayer" />
      <div ref={annotationLayerRef} className="annotationLayer" style={{ zIndex: 20, pointerEvents: "none" }} />
    </div>
  )
})
