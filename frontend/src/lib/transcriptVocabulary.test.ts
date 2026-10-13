import { describe, expect, it } from "vitest"

import { fixResultMessage, parseTerms, transcriptSourceLabel } from "./transcriptVocabulary"

describe("parseTerms", () => {
  it("splits on lines and commas, keeping the first spelling of a duplicate", () => {
    expect(parseTerms(" LanceDB \nKimi  K3, lancedb\n\n,RAG")).toEqual(["LanceDB", "Kimi K3", "RAG"])
  })

  it("is empty for blank input", () => {
    expect(parseTerms(" \n , ")).toEqual([])
  })
})

describe("transcriptSourceLabel", () => {
  it("names the source and counts only corrections that changed something", () => {
    const corrections = [
      { heard: "RAAG", term: "RAG", source: "model" as const, count: 3 },
      { heard: "Lance", term: "LanceDB", source: "user" as const, count: 0 },
    ]
    expect(transcriptSourceLabel("speech", corrections)).toBe("Speech recognition, 1 term corrected")
    expect(transcriptSourceLabel("captions", [])).toBe("Uploader's captions")
  })

  it("says nothing for a transcript ingested before the source was recorded", () => {
    expect(transcriptSourceLabel(null, [])).toBeNull()
  })
})

describe("fixResultMessage", () => {
  it("reports a fix that matched nothing as such", () => {
    const none = { occurrences: 0, chunks: 0, sections: 0, vocabulary_added: false }
    expect(fixResultMessage("Kemi", "Kimi", none)).toBe('"Kemi" does not appear in this transcript.')
  })

  it("reports the count and the vocabulary addition", () => {
    const r = { occurrences: 2, chunks: 1, sections: 1, vocabulary_added: true }
    expect(fixResultMessage("LANs-dv", "LanceDB", r)).toBe(
      'Replaced "LANs-dv" with "LanceDB" 2 times. "LanceDB" is now in your vocabulary.',
    )
  })
})
