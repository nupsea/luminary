// What the review screen is entitled to say about a card's quote.
//
// Two orthogonal checks: `grounding` proves the quote is real, `factuality` proves
// the answer follows from it. A card can pass the first and fail the second -- a
// genuine sentence quoted under an answer the passage does not support -- and that
// is the case the note has to surface, because it is the one a reviewer cannot
// otherwise see.

import { describe, expect, it } from "vitest"

import { answerCheckNote, sourceNote } from "./cardSourceNote"

describe("sourceNote", () => {
  it("says nothing reassuring about a card nobody checked", () => {
    expect(sourceNote({}).text).toMatch(/not checked/i)
  })

  it("reports a quote that is not in the document", () => {
    expect(sourceNote({ grounding: "unsupported" }).text).toMatch(/not found/i)
  })

  it("prefers the answer's failure over the quote's success", () => {
    // The dangerous card: the quote is real, so `grounding` alone reads clean.
    const note = sourceNote({ grounding: "verified", factuality: "unsupported" })
    expect(note.text).toMatch(/does not follow/i)
  })

  it("claims both only when both were checked", () => {
    expect(sourceNote({ grounding: "verified", factuality: "supported" }).text).toMatch(
      /answer follows/i,
    )
  })

  it("does not claim the answer was checked when only the quote was", () => {
    const note = sourceNote({ grounding: "verified", factuality: "unchecked" })
    expect(note.text).not.toMatch(/answer/i)
  })

  it("does not treat an unverifiable answer as a failed one", () => {
    const note = sourceNote({ grounding: "verified", factuality: "unverifiable" })
    expect(note.text).not.toMatch(/does not follow/i)
  })
})

describe("answerCheckNote", () => {
  it("says the answer is unchecked on the card sourceNote stays quiet about", () => {
    // grounding verified + factuality unchecked is the common shipped state, and
    // "Found in this document" beside it reads as an endorsement of the answer.
    const card = { grounding: "verified", factuality: "unchecked" }
    expect(sourceNote(card).text).not.toMatch(/answer/i)
    expect(answerCheckNote(card)?.text).toMatch(/has not been checked/i)
  })

  it("says nothing where sourceNote already speaks for the answer", () => {
    expect(answerCheckNote({ grounding: "verified", factuality: "supported" })).toBeNull()
    expect(answerCheckNote({ grounding: "verified", factuality: "unsupported" })).toBeNull()
  })

  it("separates could-not-check from was-not-checked", () => {
    expect(answerCheckNote({ factuality: "unverifiable" })?.text).toMatch(/could not be checked/i)
    expect(answerCheckNote({})?.text).toMatch(/has not been checked/i)
  })
})
