import { describe, expect, it, vi, beforeEach } from "vitest"
import { createLinkService } from "./pdfLinkService"

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Minimal pdfjs PDFDocumentProxy mock (same pattern as pdfTocUtils.test.ts). */
function makeDoc(overrides: Record<string, unknown> = {}) {
  return {
    numPages: 100,
    getDestination: vi.fn(),
    getPageIndex: vi.fn(),
    getPage: vi.fn(),
    ...overrides,
  } as unknown as import("pdfjs-dist").PDFDocumentProxy
}

/** Create a minimal HTMLAnchorElement-like object for addLinkAttributes tests. */
function makeLink(): HTMLAnchorElement {
  return { href: "", target: "", rel: "" } as unknown as HTMLAnchorElement
}

// ---------------------------------------------------------------------------
// navigateTo
// ---------------------------------------------------------------------------

describe("navigateTo", () => {
  let mockGoToPage: ReturnType<typeof vi.fn>

  beforeEach(() => {
    mockGoToPage = vi.fn()
  })

  it("resolves GoTo action dict with dest array to correct page number", async () => {
    const doc = makeDoc({
      getPageIndex: vi.fn().mockResolvedValue(4), // 0-based page 4
    })
    const ls = createLinkService(doc, mockGoToPage)

    await ls.navigateTo({ action: "GoTo", dest: [{ num: 4, gen: 0 }, "XYZ"] })

    // resolveDestPage converts 0-based getPageIndex(4) to 1-based 5
    expect(mockGoToPage).toHaveBeenCalledWith(5)
  })

  it("resolves GoTo action dict with D key (named destination)", async () => {
    const doc = makeDoc({
      getDestination: vi.fn().mockResolvedValue([{ num: 9, gen: 0 }, "XYZ"]),
      getPageIndex: vi.fn().mockResolvedValue(9),
    })
    const ls = createLinkService(doc, mockGoToPage)

    await ls.navigateTo({ action: "GoTo", D: "chapter-1" })

    expect(doc.getDestination).toHaveBeenCalledWith("chapter-1")
    expect(mockGoToPage).toHaveBeenCalledWith(10) // 0-based 9 -> 1-based 10
  })

  it("handles GoToR action by opening external URL", async () => {
    const openSpy = vi.fn()
    // In Vitest node env, window may not exist -- stub the global
    vi.stubGlobal("window", { open: openSpy })

    const doc = makeDoc()
    const ls = createLinkService(doc, mockGoToPage)

    await ls.navigateTo({ action: "GoToR", url: "https://example.com/other.pdf" })

    expect(openSpy).toHaveBeenCalledWith(
      "https://example.com/other.pdf",
      "_blank",
      "noopener,noreferrer",
    )
    expect(mockGoToPage).not.toHaveBeenCalled()

    vi.unstubAllGlobals()
  })

  it("resolves named string destination", async () => {
    const doc = makeDoc({
      getDestination: vi.fn().mockResolvedValue([{ num: 2, gen: 0 }, "Fit"]),
      getPageIndex: vi.fn().mockResolvedValue(2),
    })
    const ls = createLinkService(doc, mockGoToPage)

    await ls.navigateTo("my-named-dest")

    expect(doc.getDestination).toHaveBeenCalledWith("my-named-dest")
    expect(mockGoToPage).toHaveBeenCalledWith(3) // 0-based 2 -> 1-based 3
  })

  it("resolves explicit dest array", async () => {
    const doc = makeDoc({
      getPageIndex: vi.fn().mockResolvedValue(7),
    })
    const ls = createLinkService(doc, mockGoToPage)

    await ls.navigateTo([{ num: 7, gen: 0 }, "XYZ", 0, 0, 0])

    expect(mockGoToPage).toHaveBeenCalledWith(8) // 0-based 7 -> 1-based 8
  })

  it("does nothing for null/undefined dest", async () => {
    const doc = makeDoc()
    const ls = createLinkService(doc, mockGoToPage)

    await ls.navigateTo(null)
    await ls.navigateTo(undefined)

    expect(mockGoToPage).not.toHaveBeenCalled()
  })
})

// ---------------------------------------------------------------------------
// addLinkAttributes
// ---------------------------------------------------------------------------

describe("addLinkAttributes", () => {
  it("sets target=_blank and rel for external https URL", () => {
    const doc = makeDoc()
    const ls = createLinkService(doc, vi.fn())
    const link = makeLink()

    ls.addLinkAttributes(link, "https://example.com", false)

    expect(link.target).toBe("_blank")
    expect(link.rel).toContain("noopener")
    expect(link.rel).toContain("noreferrer")
  })

  it("sets target=_blank for mailto: URL", () => {
    const doc = makeDoc()
    const ls = createLinkService(doc, vi.fn())
    const link = makeLink()

    ls.addLinkAttributes(link, "mailto:x@y.com", false)

    expect(link.target).toBe("_blank")
  })

  it("sets target=_blank for tel: URL", () => {
    const doc = makeDoc()
    const ls = createLinkService(doc, vi.fn())
    const link = makeLink()

    ls.addLinkAttributes(link, "tel:+1234567890", false)

    expect(link.target).toBe("_blank")
  })

  it("does not set target for fragment-only URL", () => {
    const doc = makeDoc()
    const ls = createLinkService(doc, vi.fn())
    const link = makeLink()

    ls.addLinkAttributes(link, "#section-2", false)

    expect(link.target).toBe("")
  })

  it("sets target=_blank when newWindow is true regardless of URL", () => {
    const doc = makeDoc()
    const ls = createLinkService(doc, vi.fn())
    const link = makeLink()

    ls.addLinkAttributes(link, "#internal", true)

    expect(link.target).toBe("_blank")
  })

  it("always sets href from url parameter", () => {
    const doc = makeDoc()
    const ls = createLinkService(doc, vi.fn())
    const link = makeLink()

    ls.addLinkAttributes(link, "https://example.com/doc.pdf", false)

    expect(link.href).toBe("https://example.com/doc.pdf")
  })
})
