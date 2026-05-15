import { describe, expect, it } from "vitest"
import { buildDocActionDetail, DOC_ACTIONS } from "./docActionUtils"
import type { DocAction } from "./docActionUtils"

describe("buildDocActionDetail", () => {
  const docId = "doc-abc-123"

  it("returns learning tab for read action", () => {
    const detail = buildDocActionDetail("read", docId)
    expect(detail).toEqual({ tab: "learning", documentId: docId })
  })

  it("returns chat tab for chat action", () => {
    const detail = buildDocActionDetail("chat", docId)
    expect(detail).toEqual({ tab: "chat", documentId: docId })
  })

  it("returns study tab for study action", () => {
    const detail = buildDocActionDetail("study", docId)
    expect(detail).toEqual({ tab: "study", documentId: docId })
  })

  it("returns notes tab for notes action", () => {
    const detail = buildDocActionDetail("notes", docId)
    expect(detail).toEqual({ tab: "notes", documentId: docId })
  })

  it("returns viz tab for viz action", () => {
    const detail = buildDocActionDetail("viz", docId)
    expect(detail).toEqual({ tab: "viz", documentId: docId })
  })
})

describe("DOC_ACTIONS", () => {
  it("contains exactly five actions in correct order", () => {
    const actions: DocAction[] = ["read", "chat", "study", "notes", "viz"]
    expect(DOC_ACTIONS.map((a) => a.action)).toEqual(actions)
  })

  it("has labels for all actions", () => {
    for (const item of DOC_ACTIONS) {
      expect(item.label).toBeTruthy()
    }
  })
})
