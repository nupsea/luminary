import { describe, expect, it } from "vitest"

import { studyScopeDocumentId } from "./studyScope"

describe("studyScopeDocumentId", () => {
  it("opens the document the user chose", () => {
    expect(studyScopeDocumentId(null, "doc-1", "doc-1")).toBe("doc-1")
  })

  it("shows the landing page when nothing is chosen", () => {
    // The reported bug: clicking the Study heading clears the selection, and
    // the last-read fallback reopened that document, so the collection grid
    // could not be reached at all.
    expect(studyScopeDocumentId(null, null, "last-read-doc")).toBeNull()
  })

  it("keeps falling back when the chosen document is still ingesting", () => {
    // The user did choose something, so Study stays on a document -- the
    // readable one the hook substituted, which the page banners as a fallback.
    expect(studyScopeDocumentId(null, "ingesting-doc", "ready-doc")).toBe("ready-doc")
  })

  it("never mixes a document into a collection scope", () => {
    expect(studyScopeDocumentId("col-1", "doc-1", "doc-1")).toBeNull()
  })
})
