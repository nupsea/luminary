import { describe, expect, it } from "vitest"
import { getNodeFindInDocUrl, resolveNodeTargetDocument } from "./utils"

describe("resolveNodeTargetDocument", () => {
  it("resolves direct document_id when present", () => {
    const docId = resolveNodeTargetDocument(
      { document_id: "doc-target-1" },
      null,
    )
    expect(docId).toBe("doc-target-1")
  })

  it("prefers activeDocumentId if present in node.document_ids", () => {
    const docId = resolveNodeTargetDocument(
      { document_id: "doc-1", document_ids: ["doc-1", "doc-2"] },
      "doc-2",
    )
    expect(docId).toBe("doc-2")
  })

  it("uses node.document_id when activeDocumentId is unrelated", () => {
    const docId = resolveNodeTargetDocument(
      { document_id: "doc-target", document_ids: ["doc-target"] },
      "doc-unrelated",
    )
    expect(docId).toBe("doc-target")
  })

  it("uses first document_id if document_id is missing and activeDocumentId is unrelated", () => {
    const docId = resolveNodeTargetDocument(
      { document_ids: ["doc-first", "doc-second"] },
      "doc-unrelated",
    )
    expect(docId).toBe("doc-first")
  })

  it("falls back to activeDocumentId when node has no document attributes", () => {
    const docId = resolveNodeTargetDocument({}, "doc-active")
    expect(docId).toBe("doc-active")
  })

  it("returns null when no document is known anywhere", () => {
    const docId = resolveNodeTargetDocument({}, null)
    expect(docId).toBeNull()
  })
})

describe("getNodeFindInDocUrl", () => {
  it("generates /library?doc=...&search=... when document is resolved", () => {
    const url = getNodeFindInDocUrl(
      { label: "Hierarchical Navigable Small World", document_id: "doc-123" },
      null,
    )
    expect(url).toBe("/library?doc=doc-123&search=Hierarchical%20Navigable%20Small%20World")
  })

  it("generates /library?search=... when no document is resolved", () => {
    const url = getNodeFindInDocUrl(
      { label: "Hierarchical Navigable Small World" },
      null,
    )
    expect(url).toBe("/library?search=Hierarchical%20Navigable%20Small%20World")
  })
})
