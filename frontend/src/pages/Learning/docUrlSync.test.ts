import { describe, expect, it } from "vitest"

import { docToMirror } from "./docUrlSync"

describe("docToMirror", () => {
  it("writes the open document into an empty URL", () => {
    expect(docToMirror(null, "doc-a")).toBe("doc-a")
  })

  it("writes nothing once the URL already names the open document", () => {
    expect(docToMirror("doc-a", "doc-a")).toBeNull()
  })

  it("writes nothing when the reader is closed", () => {
    expect(docToMirror("doc-a", null)).toBeNull()
    expect(docToMirror(null, null)).toBeNull()
  })

  it("mirrors whichever document it is given -- so the caller must pass a live one", () => {
    // The shipped bug in one line. Following a Hub link to doc-b while doc-a was
    // open, the mirror effect's render still held doc-a and this returned doc-a,
    // overwriting `?doc=doc-b`. Nothing here can tell a stale id from a current
    // one, which is why the call site reads the store rather than its closure.
    expect(docToMirror("doc-b", "doc-a")).toBe("doc-a")
  })
})
