import { describe, it, expect } from "vitest"
import {
  parseLinkMarkers,
  buildLinkMarker,
  stripLinkMarkers,
  detectLinkTrigger,
  insertLinkAtTrigger,
} from "./noteLinkUtils"

describe("parseLinkMarkers", () => {
  it("parses a single [[id|text]] marker", () => {
    const result = parseLinkMarkers("Hello [[abc-123|World]] today")
    expect(result).toHaveLength(1)
    expect(result[0].id).toBe("abc-123")
    expect(result[0].text).toBe("World")
    expect(result[0].offset).toBe(6)
  })

  it("parses multiple markers in order", () => {
    const result = parseLinkMarkers("[[a|A]] and [[b|B]]")
    expect(result).toHaveLength(2)
    expect(result[0].id).toBe("a")
    expect(result[1].id).toBe("b")
  })

  it("returns empty array when no markers present", () => {
    expect(parseLinkMarkers("No links here")).toHaveLength(0)
  })

  it("returns raw token including brackets", () => {
    const result = parseLinkMarkers("[[abc-123|Gradient Descent]]")
    expect(result[0].raw).toBe("[[abc-123|Gradient Descent]]")
  })
})

describe("buildLinkMarker", () => {
  it("builds a [[id|text]] marker", () => {
    expect(buildLinkMarker("note-1", "My Note")).toBe("[[note-1|My Note]]")
  })

  it("truncates text to 60 chars", () => {
    const long = "a".repeat(80)
    const marker = buildLinkMarker("id", long)
    expect(marker).toBe(`[[id|${"a".repeat(60)}]]`)
  })

  it("strips special chars from text", () => {
    expect(buildLinkMarker("id", "Hello [World]")).toBe("[[id|Hello World]]")
  })
})

describe("stripLinkMarkers", () => {
  it("replaces [[id|text]] with [text]", () => {
    expect(stripLinkMarkers("See [[abc|Gradient Descent]] for more")).toBe(
      "See [Gradient Descent] for more"
    )
  })

  it("strips multiple markers", () => {
    expect(stripLinkMarkers("[[a|A]] and [[b|B]]")).toBe("[A] and [B]")
  })
})

describe("detectLinkTrigger", () => {
  it("returns null when no [[ present", () => {
    expect(detectLinkTrigger("Hello world", 11)).toBeNull()
  })

  it("returns partial query after [[", () => {
    expect(detectLinkTrigger("Hello [[grad", 12)).toBe("grad")
  })

  it("returns empty string when cursor is immediately after [[", () => {
    expect(detectLinkTrigger("Hello [[", 8)).toBe("")
  })

  it("returns null when [[ is already closed with ]]", () => {
    expect(detectLinkTrigger("[[id|text]] more [[", 11)).toBeNull()
  })

  it("returns the innermost partial query when [[ appears twice (lastIndexOf semantics)", () => {
    // detectLinkTrigger uses lastIndexOf("[["), so it picks up the latest trigger
    // "text [[abc [[xyz" has length 16; cursor at 16 gives before="text [[abc [[xyz"
    const s = "text [[abc [[xyz"
    expect(detectLinkTrigger(s, s.length)).toBe("xyz")
  })
})

describe("insertLinkAtTrigger", () => {
  it("replaces [[ and partial query with the link marker", () => {
    const { newValue, newCursorPos } = insertLinkAtTrigger(
      "Hello [[grad more text",
      12,
      "note-1",
      "Gradient Descent"
    )
    expect(newValue).toBe("Hello [[note-1|Gradient Descent]] more text")
    expect(newCursorPos).toBe("Hello [[note-1|Gradient Descent]]".length)
  })

  it("handles insertion at start of string", () => {
    const { newValue } = insertLinkAtTrigger("[[gr", 4, "id", "Graph")
    expect(newValue).toBe("[[id|Graph]]")
  })

  it("returns original value when no [[ found", () => {
    const { newValue, newCursorPos } = insertLinkAtTrigger("no trigger", 5, "id", "X")
    expect(newValue).toBe("no trigger")
    expect(newCursorPos).toBe(5)
  })
})
