import { describe, expect, it } from "vitest"
import { renderToStaticMarkup } from "react-dom/server"

import { ChapterPracticeSetup } from "./ChapterPracticeSetup"

const chapter = {
  id: "c1",
  title: "Chapter 1",
  order: 0,
  section_ids: ["s1"],
  page_start: 0,
  page_end: 0,
  cards: 23,
  held: 13,
  due: 10,
}

describe("ChapterPracticeSetup", () => {
  it("offers a count out of the chapter's questions, unpractised ones first", () => {
    const html = renderToStaticMarkup(
      <ChapterPracticeSetup chapter={chapter} starting={null} onStart={() => {}} />,
    )
    expect(html).toContain("10 of 23")
    expect(html).toContain('max="23"')
    expect(html).toContain("the 13 you have not practised first")
    expect(html).toContain("Recall")
    expect(html).toContain("Explain it")
  })
})
