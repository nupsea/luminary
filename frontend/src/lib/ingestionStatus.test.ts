import { describe, expect, it } from "vitest"
import { pauseNote, stageLabel } from "./ingestionStatus"

describe("stageLabel", () => {
  it("names a known stage", () => {
    expect(stageLabel("embedding", 40)).toBe("Generating embeddings")
  })

  it("falls back to the percentage for an unknown stage", () => {
    expect(stageLabel("web_refs", 72)).toBe("Processing (72%)")
  })
})

describe("pauseNote", () => {
  it("announces the pause while the document is still processing", () => {
    expect(pauseNote({ stage: "entity_extract", paused_for_interaction: true })).toMatch(
      /Paused while you're asking/,
    )
  })

  it("says nothing when indexing is running normally", () => {
    expect(pauseNote({ stage: "entity_extract", paused_for_interaction: false })).toBeNull()
  })

  it("says nothing once ingestion has finished or failed", () => {
    expect(pauseNote({ stage: "complete", paused_for_interaction: true })).toBeNull()
    expect(pauseNote({ stage: "error", paused_for_interaction: true })).toBeNull()
  })
})
