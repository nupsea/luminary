import { describe, expect, it } from "vitest"
import { renderToStaticMarkup } from "react-dom/server"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import { ChapterEndPrompt } from "./ChapterEndPrompt"

const chapter = {
  id: "c1",
  title: "Chapter 3. Storage and Retrieval",
  order: 2,
  section_ids: ["s1"],
  page_start: 0,
  page_end: 0,
  cards: 40,
  held: 40,
  due: 0,
}

describe("ChapterEndPrompt", () => {
  it("names the chapter and offers all three choices", () => {
    const html = renderToStaticMarkup(
      <QueryClientProvider client={new QueryClient()}>
        <ChapterEndPrompt documentId="d" chapter={chapter} onPractice={() => {}} onDismiss={() => {}} />
      </QueryClientProvider>,
    )
    expect(html).toContain("You finished Chapter 3. Storage and Retrieval.")
    expect(html).toContain("40 questions")
    for (const label of ["Practice", "Later", "Don&#x27;t ask for this book"]) {
      expect(html).toContain(label)
    }
  })
})
