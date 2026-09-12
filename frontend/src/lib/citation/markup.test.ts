// Marking the passage inside rendered HTML.

import { describe, expect, it } from "vitest"

import { longestPresentRun } from "./match"
import { CITATION_MARK_TOKEN, markWords } from "./markup"
import { buildCitationTarget } from "./target"

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

  it("marks a run inside the raw Markdown the words were stripped from", () => {
    // ReadView marks up the section body BEFORE it is rendered (the comment at
    // its call site: "matched against the normalised body but marked in the
    // raw one"), so `content` here still carries the backticks and bold
    // markers `normalise()` strips when the word list is built. A closing
    // backtick sitting directly against trailing punctuation ("words`,") has
    // no whitespace on either side for a `\s+`-only join to land on.
    const raw =
      "Instead of storing `document → words`, store `word → documents`: " +
      "Each entry (a **posting list**) also stores term frequency."
    const words = [
      "Instead", "of", "storing", "document", "→", "words,", "store",
      "word", "→", "documents:", "Each", "entry", "(a", "posting", "list)",
      "also", "stores", "term", "frequency.",
    ]
    const out = markWords(raw, words, "mk")
    expect(out).toContain('<mark class="mk">')
    // The whole run is one mark, not fragments broken at every backtick/bold marker.
    expect(out.match(/<mark/g)?.length).toBe(1)
    expect(out).toContain("</mark>")
  })

  it("marks the real first citation from a live /qa call (blockquote analogy)", () => {
    // Captured verbatim from a running backend: /qa against
    // retrieval_and_memory_tutorial.md asking about inverted indexes. This
    // exact source_citation + section body previously produced zero marks --
    // not a mismatch, but markWords' own "don't split an existing <mark>"
    // guard refusing a match that carried a genuine blockquote `>` character.
    const source = {
      section_heading: "1.1 The Inverted Index",
      document_title: "retrieval-and-memory-tutorial_revised",
      section_preview_snippet:
        "> **Analogy:** an inverted index is the *index at the back of a " +
        "textbook*. To find where photosynthesis is discussed, you don't read " +
        "all 900 pages (a full scan); you flip to the index — " +
        '"photosynthesis → pp. 88, 214, 302" — and jump straight there.',
    }
    const body =
      "The core data structure. Instead of storing `document → words`, store " +
      "`word → documents`:\n\n```\n\"neural\"   → [doc3, doc17, doc42]\n" +
      "\"network\"  → [doc3, doc9, doc17]\n\"protocol\" → [doc9, doc51]\n```\n\n" +
      "Each entry (a **posting list**) also stores term frequency and positions. " +
      "Query \"neural network\" becomes: fetch both posting lists, " +
      "intersect/union them, score the candidates.\n\n" +
      "> **Analogy:** an inverted index is the *index at the back of a " +
      "textbook*. To find where photosynthesis is discussed, you don't read " +
      "all 900 pages (a full scan); you flip to the index — " +
      '"photosynthesis → pp. 88, 214, 302" — and jump straight there. The ' +
      "publisher paid the indexing cost once; every reader benefits forever."

    const target = buildCitationTarget(source)
    const run = longestPresentRun(target.words, body)
    expect(run.length).toBeGreaterThan(0)

    const out = markWords(body, run, CITATION_MARK_TOKEN)
    expect(out).toContain(`<mark class="${CITATION_MARK_TOKEN}">`)
    expect(out.match(/<mark/g)?.length).toBe(1)
  })
})
