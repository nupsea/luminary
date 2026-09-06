// Matching a cited passage against text that differs from the stored chunk.

import { describe, expect, it } from "vitest"

import { endsOnWordBoundary, findRunOffsets, longestPresentRun, normalise } from "./match"

const PROSE =
  "And the revenue at 8,0,4 is 12. Now, of the three options, the vertex at 12,3,0 results " +
  "in the largest revenue."
const words = (s: string) => normalise(s).split(" ")

describe("longestPresentRun", () => {
  it("returns the whole run when the text contains it", () => {
    const w = words("And the revenue at 8,0,4 is 12. Now, of the three options")
    expect(longestPresentRun(w, PROSE).join(" ")).toBe(w.join(" "))
  })

  it("shortens to the part present, since the snippet is cut at a fixed length", () => {
    const got = longestPresentRun(words("And the revenue at 8,0,4 is 12. Now, of the zzz"), PROSE)
    expect(got.join(" ")).toMatch(/^And the revenue at 8,0,4 is 12\./)
    expect(got.join(" ")).not.toContain("zzz")
  })

  it("slides the start past material the prose never contains", () => {
    // A chunk is stored with a breadcrumb in front. Trimming only the tail keeps
    // it and finds nothing at all.
    const w = words("[Doc > Section] Now, of the three options, the vertex")
    expect(longestPresentRun(w, PROSE).join(" ")).toBe("Now, of the three options, the vertex")
  })

  it("never ends mid-word", () => {
    // "of the thr" is a substring of "of the three options"; a plain includes
    // accepts it and the highlight stops mid-word.
    expect(longestPresentRun(words("And the revenue at 8,0,4 is 12. Now, of the thr"), PROSE)
      .join(" ").endsWith("thr")).toBe(false)
  })

  it("returns nothing rather than a match too short to mean anything", () => {
    expect(longestPresentRun(words("And the"), PROSE)).toEqual([])
    expect(longestPresentRun(words("nothing here matches at all"), PROSE)).toEqual([])
  })
})

describe("endsOnWordBoundary", () => {
  it("accepts a later occurrence when the first falls inside a word", () => {
    expect(endsOnWordBoundary("cat", "concatenate the cat")).toBe(true)
    expect(endsOnWordBoundary("cat", "concatenated")).toBe(false)
  })
})

describe("findRunOffsets", () => {
  it("locates words across whitespace the chunk collapsed", () => {
    // The PDF text layer joins spans with single spaces; prose keeps paragraph
    // breaks. The same words must be findable in both.
    const raw = "HOST: Any evaluation traps?\n\nGUEST: Two big ones."
    const at = findRunOffsets(raw, ["evaluation", "traps?", "GUEST:", "Two"])
    expect(at).not.toBeNull()
    expect(raw.slice(at!.start, at!.end)).toBe("evaluation traps?\n\nGUEST: Two")
  })

  it("is null when the words are absent, and for no words", () => {
    expect(findRunOffsets(PROSE, ["nothing", "like", "this"])).toBeNull()
    expect(findRunOffsets(PROSE, [])).toBeNull()
  })
})
