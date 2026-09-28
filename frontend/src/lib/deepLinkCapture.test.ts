// A citation must land where it points, including in a document already open.

import { describe, expect, it } from "vitest"

import { arrivalFor, hasDeepLinkParams, readArrival, shouldCaptureDeepLink } from "./deepLinkCapture"

describe("arrivalFor", () => {
  const noteArrival = readArrival("doc-a", new URLSearchParams({ note: "note-1", page: "12" }))

  it("hands a document its own arrival", () => {
    expect(arrivalFor(noteArrival, "doc-a")?.noteId).toBe("note-1")
    expect(arrivalFor(noteArrival, "doc-a")?.page).toBe(12)
  })

  it("never hands one document another document's note", () => {
    // The reported bug: a note opened through ?note= on one document was still
    // held when the next document was picked from the library, and that
    // document's panel opened on it.
    expect(arrivalFor(noteArrival, "doc-b")).toBeNull()
  })

  it("reads an unparseable page as no page", () => {
    expect(readArrival("doc-a", new URLSearchParams({ page: "x" })).page).toBeUndefined()
  })
})

const params = (...names: string[]) => new URLSearchParams(names.map((n) => [n, "x"]))

describe("shouldCaptureDeepLink", () => {
  it("captures when the document changes", () => {
    expect(shouldCaptureDeepLink("doc-b", "doc-a", params())).toBe(true)
  })

  it("captures when the store already names the document but a target was given", () => {
    // The reported bug: navigateToCitation sets the active document before it
    // navigates, so the ids match on arrival and the old guard returned early,
    // dropping section_id, chunk_id and the citation snippet.
    expect(shouldCaptureDeepLink("doc-a", "doc-a", params("chunk_id"))).toBe(true)
    expect(shouldCaptureDeepLink("doc-a", "doc-a", params("section_id"))).toBe(true)
    expect(shouldCaptureDeepLink("doc-a", "doc-a", params("page"))).toBe(true)
    expect(shouldCaptureDeepLink("doc-a", "doc-a", params("search"))).toBe(true)
  })

  it("does nothing once the params have been consumed", () => {
    // This is what stops the effect looping: it clears the params, runs again,
    // and finds nothing left to act on.
    expect(shouldCaptureDeepLink("doc-a", "doc-a", params())).toBe(false)
  })

  it("does nothing with no document", () => {
    expect(shouldCaptureDeepLink(null, "doc-a", params("chunk_id"))).toBe(false)
  })

  it("ignores params that name the document rather than a place in it", () => {
    expect(hasDeepLinkParams(params("doc"))).toBe(false)
    expect(hasDeepLinkParams(params("collection_id", "sort"))).toBe(false)
  })
})
