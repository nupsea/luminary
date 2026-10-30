import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { CITATION_MARK_TOKEN } from "@/lib/citation"
import type { ChunkItem, DocumentDetail } from "./types"
import { YouTubeTranscriptView } from "./YouTubeTranscriptView"

const doc = { id: "d1", title: "Talk", created_at: "2026-10-01T00:00:00Z" } as DocumentDetail
const chunks: ChunkItem[] = [
  { id: "c1", chunk_index: 0, text: "Opening remarks.", start_time: 0 },
  { id: "c2", chunk_index: 1, text: "The cited passage.", start_time: 58 },
]

function markedChunks(citedChunkId: string | null): string[] {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(["document-chunks", doc.id], chunks)
  const html = renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <YouTubeTranscriptView doc={doc} citedChunkId={citedChunkId} />
    </QueryClientProvider>,
  )
  const tag = new RegExp(`<div[^>]*class="[^"]*${CITATION_MARK_TOKEN}[^"]*"[^>]*>`, "g")
  return [...html.matchAll(tag)].map((m) => /data-chunk-id="([^"]+)"/.exec(m[0])?.[1] ?? "")
}

describe("YouTubeTranscriptView citation mark", () => {
  it("marks exactly the cited chunk", () => {
    expect(markedChunks("c2")).toEqual(["c2"])
  })

  it("marks nothing without a citation", () => {
    expect(markedChunks(null)).toEqual([])
  })
})
