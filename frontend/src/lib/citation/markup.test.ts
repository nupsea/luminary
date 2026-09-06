// Marking the passage inside rendered HTML.

import { describe, expect, it } from "vitest"

import { CITATION_MARK_TOKEN, markWords } from "./markup"

describe("markWords", () => {
  it("marks across the paragraph breaks the chunk text collapsed", () => {
    const raw = "HOST: Any evaluation traps?\n\nGUEST: Two big ones."
    const out = markWords(raw, ["evaluation", "traps?", "GUEST:", "Two"], CITATION_MARK_TOKEN)
    expect(out).toContain(`<mark class="${CITATION_MARK_TOKEN}">`)
    expect(out).toContain("traps?\n\nGUEST:")
  })

  it("does nothing with no words or no content", () => {
    expect(markWords("prose", [], "mk")).toBe("prose")
    expect(markWords("", ["a", "b"], "mk")).toBe("")
  })

  it("skips a match that would split existing markup", () => {
    const raw = 'a <mark class="ann">b</mark> c'
    expect(markWords(raw, ["a", "b", "c"], "mk")).toBe(raw)
  })
})
