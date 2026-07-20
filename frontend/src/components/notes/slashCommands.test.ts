import { describe, expect, it } from "vitest"
import { CompletionContext } from "@codemirror/autocomplete"
import { EditorState, type TransactionSpec } from "@codemirror/state"
import type { EditorView } from "@codemirror/view"
import { setImageSizeInMarkdown, syncDocSpec } from "./markdownEditorCommands"
import { slashCommandSource, type SlashCommandConfig } from "./slashCommands"

function ctxAt(doc: string, pos = doc.length): CompletionContext {
  const state = EditorState.create({ doc, selection: { anchor: pos } })
  return new CompletionContext(state, pos, false)
}

function source(config: SlashCommandConfig = {}) {
  return slashCommandSource(() => config)
}

// The items only use view.dispatch/state, so a state-backed stub suffices.
function applyOption(
  doc: string,
  pos: number,
  label: string,
  config: SlashCommandConfig = {},
): { doc: string; anchor: number } {
  const result = source(config)(ctxAt(doc, pos))
  if (!result) throw new Error("no result")
  const opt = result.options.find((o) => o.label === label)
  if (!opt) throw new Error(`option ${label} not found`)
  let state = EditorState.create({ doc, selection: { anchor: pos } })
  const view = {
    get state() {
      return state
    },
    dispatch(spec: TransactionSpec) {
      state = state.update(spec).state
    },
  } as unknown as EditorView
  ;(opt.apply as (v: EditorView, c: unknown, f: number, t: number) => void)(view, opt, result.from, pos)
  return { doc: state.doc.toString(), anchor: state.selection.main.anchor }
}

describe("slashCommandSource", () => {
  it("triggers only at line start", () => {
    expect(source()(ctxAt("/"))).not.toBeNull()
    expect(source()(ctxAt("text\n/he"))).not.toBeNull()
    expect(source()(ctxAt("and/or"))).toBeNull()
    expect(source()(ctxAt("a /he"))).toBeNull()
  })

  it("returns null when suspended (no config)", () => {
    expect(slashCommandSource(() => undefined)(ctxAt("/"))).toBeNull()
  })

  it("filters by query and keywords", () => {
    const all = source()(ctxAt("/"))!
    const headings = source()(ctxAt("/head"))!
    expect(headings.options.length).toBe(3)
    expect(all.options.length).toBeGreaterThan(headings.options.length)
    const todo = source()(ctxAt("/todo"))!
    expect(todo.options[0].label).toBe("Task list")
  })

  it("hides Draw diagram without an onDrawDiagram callback", () => {
    const labels = (cfg: SlashCommandConfig) =>
      source(cfg)(ctxAt("/"))!.options.map((o) => o.label)
    expect(labels({})).not.toContain("Draw diagram")
    expect(labels({ onDrawDiagram: () => {} })).toContain("Draw diagram")
  })

  it("Heading 1 replaces the /query with the marker", () => {
    const { doc, anchor } = applyOption("intro\n/h1", 9, "Heading 1")
    expect(doc).toBe("intro\n# ")
    expect(anchor).toBe(8)
  })

  it("Code block places the cursor inside the fence", () => {
    const { doc, anchor } = applyOption("/code", 5, "Code block")
    expect(doc).toBe("```\n\n```\n")
    expect(anchor).toBe(4)
  })

  it("Mermaid template inserts the fenced diagram", () => {
    const { doc } = applyOption("/mer", 4, "Mermaid: Flow")
    expect(doc).toContain("```mermaid\nflowchart TD")
  })

  it("Draw diagram clears the trigger and fires the callback", () => {
    let drawn = false
    const { doc } = applyOption("/draw", 5, "Draw diagram", { onDrawDiagram: () => (drawn = true) })
    expect(doc).toBe("")
    expect(drawn).toBe(true)
  })
})

describe("setImageSizeInMarkdown", () => {
  it("adds a size pipe to a plain image", () => {
    expect(setImageSizeInMarkdown("see ![Chart](http://x/a.png) end", "http://x/a.png", "large")).toBe(
      "see ![Chart|large](http://x/a.png) end",
    )
  })

  it("replaces an existing size pipe", () => {
    expect(
      setImageSizeInMarkdown("![Chart|small](http://x/a.png)", "http://x/a.png", "medium"),
    ).toBe("![Chart|medium](http://x/a.png)")
  })

  it("maps rendered local-mirror URLs back to the authored form", () => {
    const content = "![Pasted Image|medium](__LUMINARY_IMG__/doc1/img.png)"
    const next = setImageSizeInMarkdown(
      content,
      "http://localhost:7820/images/local/doc1/img.png",
      "small",
      "http://localhost:7820",
    )
    expect(next).toBe("![Pasted Image|small](__LUMINARY_IMG__/doc1/img.png)")
  })

  it("returns content unchanged when the src is not found", () => {
    const content = "![A](http://x/a.png)"
    expect(setImageSizeInMarkdown(content, "http://x/other.png", "large")).toBe(content)
  })
})

describe("syncDocSpec", () => {
  function applySync(doc: string, caret: number, value: string) {
    const state = EditorState.create({ doc, selection: { anchor: caret } })
    const spec = syncDocSpec(state, value)
    if (!spec) return { doc, anchor: caret, dispatched: false }
    const next = state.update(spec).state
    return { doc: next.doc.toString(), anchor: next.selection.main.anchor, dispatched: true }
  }

  it("is a no-op when the value already matches the doc", () => {
    expect(syncDocSpec(EditorState.create({ doc: "hello world" }), "hello world")).toBeNull()
  })

  it("seeds an empty view and lands the caret at the end", () => {
    const r = applySync("", 0, "loaded body")
    expect(r.doc).toBe("loaded body")
    expect(r.anchor).toBe("loaded body".length)
  })

  it("keeps the caret put when an edit lands after it", () => {
    const r = applySync("![Chart](x.png) tail", 3, "![Chart|large](x.png) tail")
    expect(r.doc).toBe("![Chart|large](x.png) tail")
    expect(r.anchor).toBe(3)
  })

  it("carries the caret forward when an edit lands before it", () => {
    const r = applySync("intro body", 10, "intro extra body")
    expect(r.doc).toBe("intro extra body")
    expect(r.anchor).toBe(16)
  })

  it("does not eject the caret to the document start", () => {
    const r = applySync("aaa bbb ccc", 5, "aaa bXb ccc")
    expect(r.anchor).not.toBe(0)
  })
})
