import { describe, expect, it } from "vitest"

import {
  type Chapter,
  chapterIndexAt,
  finishedChapter,
  pickChapter,
  worthOffering,
} from "./chapterApi"

function chapter(id: string, sections: string[], cards: number, held: number): Chapter {
  return { id, title: id, order: 0, section_ids: sections, page_start: 0, page_end: 0, cards, held, due: 0 }
}

const book = [
  chapter("c1", ["s1", "s2"], 5, 5),
  chapter("c2", ["s3"], 4, 0),
  chapter("c3", ["s4"], 0, 0),
]

describe("chapter end", () => {
  it("finds the chapter from the Read view's section", () => {
    const at = (sectionId: string) => chapterIndexAt(book, { sectionId })
    expect([at("s2"), at("s3"), at("s4"), at("front")]).toEqual([0, 1, 2, undefined])
  })

  it("finds the chapter from the PDF view's page", () => {
    // Pages as a PDF book has them: front matter, chapter 1 at 32-56, a blank 57, chapter 2.
    const pdf = [
      { ...book[0], page_start: 32, page_end: 56 },
      { ...book[1], page_start: 58, page_end: 72 },
      { ...book[2], page_start: 0, page_end: 0 },
    ]
    const at = (page: number) => chapterIndexAt(pdf, { page })
    expect([at(10), at(32), at(56), at(57), at(58), at(72), at(0)]).toEqual([
      undefined, 0, 0, undefined, 1, 1, undefined,
    ])
  })

  it("a chapter ends only when reading moves forward into a later one", () => {
    expect(finishedChapter(book, 0, 1)?.id).toBe("c1")
    expect(finishedChapter(book, 1, 0)).toBeNull()
    expect(finishedChapter(book, 0, 0)).toBeNull()
    expect(finishedChapter(book, undefined, 1)).toBeNull()
  })

  it("offers practice only for a chapter with unpractised cards", () => {
    expect(book.map(worthOffering)).toEqual([true, false, false])
  })
})

describe("random chapter", () => {
  it("never picks a chapter without cards", () => {
    for (const r of [0, 0.5, 0.99]) expect(pickChapter(book, () => r)?.id).not.toBe("c3")
  })

  it("weights unpractised chapters three to one", () => {
    // Weights 3 (c1) and 1 (c2): the first three quarters of the range pick c1.
    expect(pickChapter(book, () => 0.74)?.id).toBe("c1")
    expect(pickChapter(book, () => 0.76)?.id).toBe("c2")
  })

  it("is null when no chapter has cards", () => {
    expect(pickChapter([chapter("x", ["s"], 0, 0)])).toBeNull()
  })
})
