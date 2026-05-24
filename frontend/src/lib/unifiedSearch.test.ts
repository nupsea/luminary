/**
 * Pure-function tests for the unified search adapters (2D.3).
 */

import { describe, expect, it } from "vitest"

import {
  adaptDocumentResults,
  adaptFlashcardResults,
  adaptNoteResults,
} from "./unifiedSearch"

describe("adaptDocumentResults", () => {
  it("flattens DocumentGroup matches into UnifiedSearchResult rows", () => {
    const out = adaptDocumentResults({
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      results: [
        {
          document_id: "doc-1",
          document_title: "The Time Machine",
          content_type: "book",
          matches: [
            {
              chunk_id: "c1",
              document_id: "doc-1",
              section_heading: "Chapter 1",
              page: 12,
              text_excerpt: "I was sitting in my drawing-room",
              score: 0.9,
            },
            {
              chunk_id: "c2",
              document_id: "doc-1",
              section_heading: "",
              page: 0,
              text_excerpt: "the Time Traveller began",
              score: 0.4,
            },
          ],
        } as any,
      ],
    } as any)
    expect(out).toHaveLength(2)
    expect(out[0]).toMatchObject({
      kind: "document",
      id: "c1",
      title: "The Time Machine",
      contentType: "book",
      documentId: "doc-1",
      context: "Chapter 1 · p.12",
    })
    expect(out[1].context).toBe("")
  })
})

describe("adaptNoteResults", () => {
  it("derives a title from the first non-markdown line and trims snippet", () => {
    const out = adaptNoteResults({
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      results: [
        {
          note_id: "n1",
          content: "# A heading\nbody text follows",
          tags: ["ml", "python"],
          group_name: null,
          document_id: "doc-1",
          score: 0.8,
          source: "fts",
        } as any,
      ],
    } as any)
    expect(out[0].kind).toBe("note")
    expect(out[0].title).toBe("A heading")
    expect(out[0].context).toBe("ml, python")
    expect(out[0].documentId).toBe("doc-1")
  })

  it("falls back to 'Untitled note' on empty content", () => {
    const out = adaptNoteResults({
      results: [
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        { note_id: "n2", content: "", tags: [], group_name: null, document_id: null, score: 0.1, source: "fts" } as any,
      ],
    } as any)
    expect(out[0].title).toBe("Untitled note")
  })
})

describe("adaptFlashcardResults", () => {
  it("maps question/answer into title/snippet and uses a default score", () => {
    const out = adaptFlashcardResults({
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      items: [
        {
          id: "f1",
          document_id: "doc-1",
          question: "What is gravity?",
          answer: "A force.",
          flashcard_type: "qa",
        } as any,
      ],
      total: 1,
      page: 1,
      page_size: 10,
    } as any)
    expect(out[0]).toMatchObject({
      kind: "flashcard",
      id: "f1",
      title: "What is gravity?",
      snippet: "A force.",
      contentType: "flashcard",
    })
    expect(out[0].score).toBe(0.5)
  })
})
