import { describe, expect, it } from "vitest"

import { humanizeTitle } from "./humanizeTitle"

describe("humanizeTitle", () => {
  it("reads a filename as a title", () => {
    // Measured on one library: 36 of 53 stored titles are the filename the
    // document arrived as, because that is all the source gave us.
    expect(humanizeTitle("sherlock_holmes")).toBe("Sherlock Holmes")
    expect(humanizeTitle("moby-dick")).toBe("Moby Dick")
    expect(humanizeTitle("daily_thoughts_2026")).toBe("Daily Thoughts 2026")
  })

  it("keeps small words small, except first", () => {
    expect(humanizeTitle("art_of_unix")).toBe("Art of Unix")
    expect(humanizeTitle("retrieval-and-memory-tutorial")).toBe("Retrieval and Memory Tutorial")
    expect(humanizeTitle("the_odyssey")).toBe("The Odyssey")
  })

  it("leaves a title that already reads as one completely alone", () => {
    // The bracketing case. Touching these would be rewriting a real title, and
    // a parser-extracted title is the good case, not the one to repair.
    const real = "Durable Offline Writes: Lessons from Seven Sync Engines"
    expect(humanizeTitle(real)).toBe(real)
    expect(humanizeTitle("Attention? Attention! | Lil'Log")).toBe("Attention? Attention! | Lil'Log")
  })

  it("does not flatten capitals the author chose", () => {
    // `Ddia` would be a worse title than `DDIA`, not a better one.
    expect(humanizeTitle("DDIA")).toBe("DDIA")
    expect(humanizeTitle("Approximations")).toBe("Approximations")
    expect(humanizeTitle("ibm-SDM-vol-2")).toBe("Ibm SDM Vol 2")
  })

  it("drops a file extension but not a version number", () => {
    expect(humanizeTitle("art_of_unix.pdf")).toBe("Art of Unix")
    expect(humanizeTitle("audit_unseen_arxiv_2508.03858")).toBe("Audit Unseen Arxiv 2508.03858")
  })

  it("survives titles with nothing in them", () => {
    expect(humanizeTitle("")).toBe("")
    expect(humanizeTitle("   ")).toBe("")
    expect(humanizeTitle("___")).toBe("___")
  })
})

describe("acronyms inside a filename", () => {
  it("uppercases a short token with no vowel", () => {
    // Found by running this over a real library rather than over fixtures.
    expect(humanizeTitle("sutton_barto_rl")).toBe("Sutton Barto RL")
    expect(humanizeTitle("matrix_calculus_for_dl")).toBe("Matrix Calculus for DL")
    expect(humanizeTitle("radiology_chexnet_cxr")).toBe("Radiology Chexnet CXR")
    expect(humanizeTitle("d2l_dive_into_deep_learning")).toBe("D2L Dive Into Deep Learning")
  })

  it("leaves a word alone even when it is short", () => {
    // `y` counts as a vowel, so a title opening with "by" is not an acronym.
    expect(humanizeTitle("by_the_sea")).toBe("By the Sea")
    expect(humanizeTitle("the_gita")).toBe("The Gita")
    // Vowels and four letters: indistinguishable from a word, so left as one.
    expect(humanizeTitle("ddia_new")).toBe("Ddia New")
  })
})
