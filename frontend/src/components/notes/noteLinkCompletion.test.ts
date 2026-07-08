import { describe, expect, it, vi } from "vitest"
import { CompletionContext } from "@codemirror/autocomplete"
import { EditorState } from "@codemirror/state"
import {
  linkLabel,
  noteLinkCompletionSource,
  type NoteLinkCompletionConfig,
} from "./noteLinkCompletion"

function ctxAt(doc: string, pos = doc.length): CompletionContext {
  const state = EditorState.create({ doc, selection: { anchor: pos } })
  return new CompletionContext(state, pos, false)
}

function makeConfig(overrides: Partial<NoteLinkCompletionConfig> = {}): NoteLinkCompletionConfig {
  return {
    fetchCandidates: vi.fn(async () => [
      { id: "aaa", preview: "First note about graphs" },
      { id: "bbb", preview: "# Second note\nbody" },
    ]),
    ...overrides,
  }
}

describe("noteLinkCompletionSource", () => {
  it("returns null without a [[ trigger", async () => {
    const source = noteLinkCompletionSource(() => makeConfig())
    expect(await source(ctxAt("plain text"))).toBeNull()
  })

  it("triggers on [[ and passes the partial query to the fetcher", async () => {
    const config = makeConfig()
    const source = noteLinkCompletionSource(() => config)
    const result = await source(ctxAt("see [[gra"))
    expect(result).not.toBeNull()
    expect(config.fetchCandidates).toHaveBeenCalledWith("gra")
    expect(result!.from).toBe(4)
    expect(result!.options).toHaveLength(2)
  })

  it("does not trigger once the link is closed", async () => {
    const source = noteLinkCompletionSource(() => makeConfig())
    expect(await source(ctxAt("see [[aaa|Done]] after"))).toBeNull()
  })

  it("excludes the note being edited", async () => {
    const source = noteLinkCompletionSource(() => makeConfig({ excludeId: () => "aaa" }))
    const result = await source(ctxAt("[["))
    expect(result!.options).toHaveLength(1)
    expect(result!.options[0].label).toContain("Second note")
  })

  it("returns null when the fetcher fails", async () => {
    const source = noteLinkCompletionSource(() =>
      makeConfig({ fetchCandidates: vi.fn(async () => Promise.reject(new Error("down"))) }),
    )
    expect(await source(ctxAt("[[q"))).toBeNull()
  })

  it("returns null when suspended (no config)", async () => {
    const source = noteLinkCompletionSource(() => undefined)
    expect(await source(ctxAt("[[q"))).toBeNull()
  })
})

describe("linkLabel", () => {
  it("strips heading markers and marker-unsafe characters", () => {
    expect(linkLabel("# My [note] about `code`\nrest")).toBe("My note about code")
  })

  it("truncates long previews", () => {
    const label = linkLabel("x".repeat(120))
    expect(label.length).toBeLessThanOrEqual(63)
    expect(label.endsWith("...")).toBe(true)
  })

  it("falls back for empty previews", () => {
    expect(linkLabel("   \n ")).toBe("Untitled note")
  })
})
