import { describe, expect, it } from "vitest"

import { readerLandingTab } from "./readerLandingTab"

describe("readerLandingTab", () => {
  it("opens a non-PDF document in the universal reader", () => {
    // The reported bug: these formats matched no branch and kept the initial
    // "sections" state, so opening an article landed on its table of contents.
    for (const format of ["html", "md", "docx", "txt", "youtube"]) {
      expect(readerLandingTab(format, false)).toBe("read")
    }
  })

  it("opens a PDF in the PDF viewer, deep link or not", () => {
    expect(readerLandingTab("pdf", false)).toBe("pdfview")
    expect(readerLandingTab("pdf", true)).toBe("pdfview")
  })

  it("opens an EPUB in the book viewer", () => {
    expect(readerLandingTab("epub", false)).toBe("bookview")
  })

  it("sends a deep link to the Read view, which can scroll to the passage", () => {
    expect(readerLandingTab("epub", true)).toBe("read")
    expect(readerLandingTab("html", true)).toBe("read")
  })

  it("never lands on the section list", () => {
    for (const format of [undefined, "pdf", "epub", "html", "unknown"]) {
      for (const deepLink of [false, true]) {
        expect(readerLandingTab(format, deepLink)).not.toBe("sections")
      }
    }
  })
})
