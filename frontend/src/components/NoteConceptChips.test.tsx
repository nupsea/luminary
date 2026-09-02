import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { NoteConceptChips } from "./NoteConceptChips"

const html = () =>
  renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <NoteConceptChips noteId="n1" noteTitle="Search Algos" />
    </QueryClientProvider>,
  )

describe("NoteConceptChips", () => {
  it("offers both writing cards and studying them", () => {
    // A note page carried only "Quiz me", which opens the Study Launcher on
    // cards that already exist. A note with none offered nothing at the moment
    // the reader wants them, and no other surface generates from one note (#113).
    const out = html()
    expect(out).toContain("Make cards")
    expect(out).toContain("Quiz me on this note")
  })
})
