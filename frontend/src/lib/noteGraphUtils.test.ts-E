import { describe, it, expect } from "vitest"
import {
  NOTE_NODE_COLOR,
  computeNoteNodeSize,
  noteNodeAttrs,
  buildNoteNavigateDetail,
} from "./noteGraphUtils"

describe("computeNoteNodeSize", () => {
  it("returns minimum size 8 for 0 links", () => {
    expect(computeNoteNodeSize(0)).toBe(8)
  })

  it("returns minimum size 8 for 1 link", () => {
    expect(computeNoteNodeSize(1)).toBe(8)
  })

  it("returns scaled size for 4 links (sqrt(4)*5 = 10)", () => {
    expect(computeNoteNodeSize(4)).toBe(10)
  })

  it("returns larger size for more links", () => {
    expect(computeNoteNodeSize(9)).toBeGreaterThan(computeNoteNodeSize(4))
  })
})

describe("noteNodeAttrs", () => {
  it("returns correct color for Note nodes", () => {
    const attrs = noteNodeAttrs("My note", "note-1", 3)
    expect(attrs.color).toBe(NOTE_NODE_COLOR)
    expect(attrs.color).toBe("#6366f1")
  })

  it("returns 'square' type for Note nodes", () => {
    const attrs = noteNodeAttrs("My note", "note-1", 3)
    expect(attrs.type).toBe("square")
  })

  it("sets entityType to 'note'", () => {
    const attrs = noteNodeAttrs("Note label", "note-42", 0)
    expect(attrs.entityType).toBe("note")
  })

  it("sets note_id correctly", () => {
    const attrs = noteNodeAttrs("Note label", "note-42", 5)
    expect(attrs.note_id).toBe("note-42")
  })

  it("sets label correctly", () => {
    const attrs = noteNodeAttrs("First 40 chars of content", "n1", 1)
    expect(attrs.label).toBe("First 40 chars of content")
  })
})

describe("buildNoteNavigateDetail", () => {
  it("returns correct tab and filter for luminary:navigate event", () => {
    const detail = buildNoteNavigateDetail("note-123")
    expect(detail.tab).toBe("notes")
    expect(detail.filter).toBe("note-123")
  })

  it("preserves note ID exactly", () => {
    const id = "550e8400-e29b-41d4-a716-446655440000"
    const detail = buildNoteNavigateDetail(id)
    expect(detail.filter).toBe(id)
  })
})
