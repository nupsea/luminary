import { describe, expect, it } from "vitest"
import { renderToStaticMarkup } from "react-dom/server"
import { FacetChips } from "./FacetChips"
import type { DocumentFacets } from "./types"

const html = (facets: DocumentFacets | null) =>
  renderToStaticMarkup(<FacetChips facets={facets} />)

describe("FacetChips", () => {
  it("shows the classification and the card strategy it implies", () => {
    const out = html({
      form: "reference",
      domain: "technical",
      register: null,
      card_genre: "technical",
    })
    expect(out).toContain("reference")
    expect(out).toContain("technical")
    expect(out).toContain("cards")
  })

  it("says unclassified rather than inventing a default", () => {
    // Four of the library's eight talks reach this state: the transcript probe
    // returned nothing. Calling that "general" would show the reader a decision
    // that never happened, which is the thing this strip exists to let them check.
    const out = html({
      form: "dialogue",
      domain: null,
      register: null,
      card_genre: "conversation",
    })
    expect(out).not.toContain("general")
    expect(out.match(/unclassified/g)).toHaveLength(2)
  })

  it("renders nothing when the document has no facets", () => {
    expect(html(null)).toBe("")
  })

  it("renders nothing when form is missing, rather than a strip of blanks", () => {
    expect(html({ form: null, domain: null, register: null, card_genre: null })).toBe("")
  })
})
