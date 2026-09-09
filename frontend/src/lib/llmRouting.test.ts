// The summary sentence must be computed from the rows, not chosen by mode.
//
// Three hardcoded sentences used to sit under the mode cards, and one asserted
// that flashcards stayed local in hybrid -- which card generation does not do.
// These cases pin the property that made that possible impossible: the sentence
// names exactly the rows whose `on_device` is false, whatever they turn out to be.

import { describe, expect, it } from "vitest"

import { egressSummary, type RoutingResponse, type WorkRoutingItem } from "./llmRouting"

function row(id: string, label: string, onDevice: boolean): WorkRoutingItem {
  return {
    id,
    label,
    model: onDevice ? `ollama/${id}` : `openai/${id}`,
    on_device: onDevice,
    routable: true,
    why: "",
    fallback_reason: null,
  }
}

function report(work: WorkRoutingItem[], provider: string | null = "openai"): RoutingResponse {
  return {
    mode: provider ? "hybrid" : "private",
    provider,
    work,
    leaves_device: work.filter((w) => !w.on_device).map((w) => w.id),
  }
}

describe("egressSummary", () => {
  it("says nothing leaves when every row is on-device", () => {
    const text = egressSummary(report([row("answering", "Answering your question", true)], null))
    expect(text).toContain("Nothing leaves this machine")
  })

  it("names the single row that leaves, and the provider it reaches", () => {
    const text = egressSummary(report([
      row("indexing", "Indexing your library", true),
      row("answering", "Answering your question", false),
    ]))
    expect(text).toContain("answering your question")
    expect(text).toContain("openai")
    expect(text).not.toContain("indexing your library")
  })

  it("names every row that leaves, not just the first", () => {
    // The case the old prose got wrong: two interactive rows leave in hybrid,
    // and a sentence that mentions only chat understates what was sent.
    const text = egressSummary(report([
      row("enrichment", "Summaries, tags and titles at ingest", true),
      row("study_material", "Writing cards and study material", false),
      row("answering", "Answering your question", false),
    ]))
    expect(text).toContain("writing cards and study material")
    expect(text).toContain("answering your question")
  })

  it("still names a provider when none is configured", () => {
    const text = egressSummary(report([row("answering", "Answering your question", false)], null))
    expect(text).toContain("your provider")
  })
})
