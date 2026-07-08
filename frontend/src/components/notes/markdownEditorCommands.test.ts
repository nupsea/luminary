import { describe, expect, it } from "vitest"
import { EditorState, type StateCommand, type TransactionSpec } from "@codemirror/state"
import {
  deleteMarkupBackward,
  insertNewlineContinueMarkup,
  markdown,
  markdownLanguage,
} from "@codemirror/lang-markdown"
import {
  insertBlockSpec,
  insertInlineSpec,
  replaceSelectionSpec,
  toggleInlineMarkSpec,
} from "./markdownEditorCommands"

function mdState(doc: string, cursor = doc.length): EditorState {
  return EditorState.create({
    doc,
    selection: { anchor: cursor },
    extensions: [markdown({ base: markdownLanguage })],
  })
}

function apply(state: EditorState, spec: TransactionSpec): EditorState {
  return state.update(spec).state
}

function press(state: EditorState, cmd: StateCommand): EditorState {
  let next = state
  const handled = cmd({ state, dispatch: (tr) => (next = tr.state) })
  expect(handled).toBe(true)
  return next
}

describe("insertBlockSpec", () => {
  it("pads with blank lines mid-text", () => {
    const state = mdState("before", 6)
    const next = apply(state, insertBlockSpec(state, "```mermaid\nx\n```"))
    expect(next.doc.toString()).toBe("before\n\n```mermaid\nx\n```\n\n")
  })

  it("adds no leading padding at doc start", () => {
    const state = mdState("", 0)
    const next = apply(state, insertBlockSpec(state, "block"))
    expect(next.doc.toString()).toBe("block\n\n")
  })

  it("skips trailing padding when a newline follows", () => {
    const state = mdState("a\n\nb", 1)
    const next = apply(state, insertBlockSpec(state, "block"))
    expect(next.doc.toString()).toBe("a\n\nblock\n\nb")
  })
})

describe("toggleInlineMarkSpec", () => {
  it("wraps a selection in markers", () => {
    const state = EditorState.create({ doc: "some word here", selection: { anchor: 5, head: 9 } })
    const next = apply(state, toggleInlineMarkSpec(state, "**"))
    expect(next.doc.toString()).toBe("some **word** here")
  })

  it("unwraps when the selection includes the markers", () => {
    const state = EditorState.create({ doc: "some **word** here", selection: { anchor: 5, head: 13 } })
    const next = apply(state, toggleInlineMarkSpec(state, "**"))
    expect(next.doc.toString()).toBe("some word here")
  })

  it("unwraps when markers sit just outside the selection", () => {
    const state = EditorState.create({ doc: "some **word** here", selection: { anchor: 7, head: 11 } })
    const next = apply(state, toggleInlineMarkSpec(state, "**"))
    expect(next.doc.toString()).toBe("some word here")
  })

  it("empty selection inserts a pair with the cursor inside", () => {
    const state = mdState("go ", 3)
    const next = apply(state, toggleInlineMarkSpec(state, "*"))
    expect(next.doc.toString()).toBe("go **")
    expect(next.selection.main.anchor).toBe(4)
  })
})

describe("replaceSelectionSpec", () => {
  it("rewrites an image size pipe on the selection", () => {
    const doc = "see ![Chart|small](img.png) end"
    const state = EditorState.create({ doc, selection: { anchor: 4, head: 27 } })
    const next = apply(
      state,
      replaceSelectionSpec(state, (sel) =>
        sel.replace(/!\[([^\]|]*)(?:\|[^\]]*)?\]/, "![$1|large]"),
      ),
    )
    expect(next.doc.toString()).toBe("see ![Chart|large](img.png) end")
  })
})

describe("insertInlineSpec", () => {
  it("inserts at the cursor without padding", () => {
    const state = mdState("ab", 1)
    const next = apply(state, insertInlineSpec(state, "X"))
    expect(next.doc.toString()).toBe("aXb")
  })
})

describe("markdown continuation (headless CM commands)", () => {
  it("continues a bullet list on Enter", () => {
    const next = press(mdState("- item"), insertNewlineContinueMarkup)
    expect(next.doc.toString()).toBe("- item\n- ")
  })

  it("continues a numbered list with the next index", () => {
    const next = press(mdState("1. alpha"), insertNewlineContinueMarkup)
    expect(next.doc.toString()).toBe("1. alpha\n2. ")
  })

  it("continues a task list with an unchecked box", () => {
    const next = press(mdState("- [x] done"), insertNewlineContinueMarkup)
    expect(next.doc.toString()).toBe("- [x] done\n- [ ] ")
  })

  it("continues a blockquote", () => {
    const next = press(mdState("> quoted"), insertNewlineContinueMarkup)
    expect(next.doc.toString()).toBe("> quoted\n> ")
  })

  it("backspace strips the empty list marker (keeps indent, per CM semantics)", () => {
    const next = press(mdState("- item\n- "), deleteMarkupBackward)
    expect(next.doc.toString()).toBe("- item\n  ")
  })
})
