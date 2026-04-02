/**
 * PDF link service factory.
 *
 * Extracted from PDFViewer.tsx so link resolution logic can be unit-tested
 * independently of the React component and the pdfjs worker.
 */
import type { PDFDocumentProxy } from "pdfjs-dist"
import { resolveDestPage } from "./pdfTocUtils"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface PdfLinkService {
  externalLinkTarget: number
  externalLinkRel: string
  externalLinkEnabled: boolean
  getDestinationHash: (dest: any) => string // pdf.js destination type is untyped
  getAnchorUrl: (hash: string) => string
  setHash: (hash: string) => void
  executeNamedAction: (action: string) => void
  cachePageRef: (ref: any, pageIndex: number) => void // pdf.js ref type is untyped
  addLinkAttributes: (link: HTMLAnchorElement, url: string, newWindow: boolean) => void
  navigateTo: (dest: unknown) => Promise<void>
  goToDestination: (dest: unknown) => Promise<void>
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Protocols that should open externally (new tab / default handler). */
const EXTERNAL_PROTOCOLS = ["http:", "https:", "mailto:", "tel:"]

function isExternalUrl(url: string): boolean {
  // Fragment-only or empty URLs are internal
  if (!url || url.startsWith("#")) return false
  return EXTERNAL_PROTOCOLS.some((p) => url.startsWith(p))
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/**
 * Create a pdfjs-compatible link service that resolves internal destinations
 * (including GoTo action dictionaries) and opens external URLs properly.
 */
export function createLinkService(
  pdfDoc: PDFDocumentProxy,
  goToPage: (n: number) => void,
): PdfLinkService {
  const service: PdfLinkService = {
    externalLinkTarget: 2, // BLANK
    externalLinkRel: "noopener noreferrer nofollow",
    externalLinkEnabled: true,
    getDestinationHash: (dest: any) => "#", // pdf.js destination type is untyped
    getAnchorUrl: (hash: string) => "#",
    setHash: (hash: string) => { /* no-op: required by pdf.js link service interface */ },
    executeNamedAction: (action: string) => { /* no-op: required by pdf.js link service interface */ },
    cachePageRef: (ref: any, pageIndex: number) => { /* no-op: required by pdf.js link service interface */ }, // pdf.js ref type is untyped

    addLinkAttributes(link: HTMLAnchorElement, url: string, newWindow: boolean) {
      if (url) {
        link.href = url
        // Always set target/rel for external protocols regardless of newWindow flag
        if (newWindow || isExternalUrl(url)) {
          link.target = "_blank"
          link.rel = "noopener noreferrer nofollow"
        }
      } else {
        // Internal link - ensure it's clickable and intercept click
        link.href = "#"
        // PDF.js often uses an onclick listener that calls goToDestination.
        // We ensure that clicking our intercepted link also works.
        link.onclick = (e) => {
          e.preventDefault()
          // pdfjs stores the destination in the link element's data
          const dest = (link as any).pdfDest || (link as any).dataset.pdfDest
          if (dest) {
            void this.navigateTo(dest)
          }
        }
      }
    },

    async navigateTo(dest: unknown) {
      if (!dest) return

      // Handle GoTo / GoToR action dictionaries
      // pdfjs sometimes passes { action: "GoTo", dest: [...] } or { action: "GoTo", D: [...] }
      if (dest !== null && typeof dest === "object" && !Array.isArray(dest)) {
        const obj = dest as Record<string, unknown>
        const action = obj.action as string | undefined

        if (action === "GoToR") {
          // Remote GoTo -- open as external link if URL is present
          const fileUrl = (obj.url as string) || (obj.filename as string)
          if (fileUrl) {
            window.open(fileUrl, "_blank", "noopener,noreferrer")
          }
          return
        }

        // GoTo action or any action with dest/D -- unwrap the destination
        const innerDest = obj.dest ?? obj.D
        if (innerDest) {
          // Recurse with the unwrapped destination (string or array)
          await this.navigateTo(innerDest)
          return
        }
      }

      // Named destination (string) or explicit dest array
      const pageNum = await resolveDestPage(pdfDoc, dest as string | Array<unknown>)
      if (pageNum > 0) {
        goToPage(pageNum)
      }
    },

    async goToDestination(dest: unknown) {
      return this.navigateTo(dest)
    },
  }
  return service
}
