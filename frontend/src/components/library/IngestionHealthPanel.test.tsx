import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { IngestionHealthPanel } from "./IngestionHealthPanel"

const html = (entity_chunks_scanned: number | null) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(["diagnostics", "d1"], {
    chunk_count: 20708,
    fts_count: 20708,
    vector_count: 20708,
    entity_count: 184,
    entity_chunks_scanned,
    edge_count: 900,
  })
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <IngestionHealthPanel documentId="d1" stage="complete" />
    </QueryClientProvider>,
  )
}

describe("IngestionHealthPanel", () => {
  it("says the entity count covers a sample of a long document (#63)", () => {
    expect(html(500)).toContain("from 500 of 20,708 chunks")
  })

  it("adds nothing when every chunk was read, or the count predates it", () => {
    expect(html(20708)).not.toContain("chunks</p>")
    expect(html(null)).not.toContain(" of 20,708")
  })
})
