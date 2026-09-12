import { describe, expect, it } from "vitest"
import { EditorState, type StateCommand, type TransactionSpec } from "@codemirror/state"
import {
  deleteMarkupBackward,
  insertNewlineContinueMarkup,
  markdown,
  markdownLanguage,
} from "@codemirror/lang-markdown"
import {
  findEnclosingBlock,
  insertBlockBreakSpec,
  insertBlockSpec,
  insertInlineSpec,
  moveBlockOrLineSpec,
  replaceSelectionSpec,
  tableNextCellSpec,
  tablePrevCellSpec,
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

describe("findEnclosingBlock", () => {
  it("detects a math block", () => {
    const doc = "before\n$$\nx = 1\n$$\nafter"
    const state = mdState(doc, 12) // inside x = 1
    const block = findEnclosingBlock(state, 12)
    expect(block).not.toBeNull()
    expect(block?.type).toBe("math")
    expect(state.sliceDoc(block!.from, block!.to)).toBe("$$\nx = 1\n$$")
  })

  it("detects a markdown table", () => {
    const doc = "| A | B |\n|---|---|\n| 1 | 2 |"
    const state = mdState(doc, 22) // inside row 2
    const block = findEnclosingBlock(state, 22)
    expect(block).not.toBeNull()
    expect(block?.type).toBe("table")
    expect(state.sliceDoc(block!.from, block!.to)).toBe(doc)
  })
})

describe("moveBlockOrLineSpec (swapping blocks like LaTeX above/below Table)", () => {
  it("moves a LaTeX block down past a Table", () => {
    const doc = "$$\n\\int x dx\n$$\n\n| Col A | Col B |\n|---|---|\n| 1 | 2 |"
    const state = mdState(doc, 5) // inside LaTeX block
    const spec = moveBlockOrLineSpec(state, 1)
    expect(spec).not.toBeNull()
    const next = apply(state, spec!)
    expect(next.doc.toString()).toBe(
      "| Col A | Col B |\n|---|---|\n| 1 | 2 |\n\n$$\n\\int x dx\n$$",
    )
  })

  it("moves a LaTeX block up past a Table", () => {
    const doc = "| Col A | Col B |\n|---|---|\n| 1 | 2 |\n\n$$\n\\int x dx\n$$"
    const state = mdState(doc, 48) // inside LaTeX block
    const spec = moveBlockOrLineSpec(state, -1)
    expect(spec).not.toBeNull()
    const next = apply(state, spec!)
    expect(next.doc.toString()).toBe(
      "$$\n\\int x dx\n$$\n\n| Col A | Col B |\n|---|---|\n| 1 | 2 |",
    )
  })

  it("moves a single normal line up and down", () => {
    const doc = "line 1\nline 2\nline 3"
    const state = mdState(doc, 9) // inside line 2
    const downSpec = moveBlockOrLineSpec(state, 1)
    expect(downSpec).not.toBeNull()
    const downState = apply(state, downSpec!)
    expect(downState.doc.toString()).toBe("line 1\nline 3\nline 2")

    const upSpec = moveBlockOrLineSpec(state, -1)
    expect(upSpec).not.toBeNull()
    const upState = apply(state, upSpec!)
    expect(upState.doc.toString()).toBe("line 2\nline 1\nline 3")
  })
})

describe("tableNextCellSpec (Tab in tables)", () => {
  it("moves to the next cell in the same row", () => {
    const doc = "| Col A | Col B |"
    const state = mdState(doc, 3) // inside Col A
    const spec = tableNextCellSpec(state)
    expect(spec).not.toBeNull()
    const next = apply(state, spec!)
    expect(next.selection.main.anchor).toBe(10) // inside Col B
  })

  it("moves to the next row skipping the separator row", () => {
    const doc = "| Col A | Col B |\n|---|---|\n| 1 | 2 |"
    const state = mdState(doc, 11) // inside Col B on header row
    const spec = tableNextCellSpec(state)
    expect(spec).not.toBeNull()
    const next = apply(state, spec!)
    // Should land inside the data row | 1 | 2 | on cell '1'
    expect(next.doc.lineAt(next.selection.main.anchor).text).toBe("| 1 | 2 |")
  })

  it("appends a new row when pressing Tab on the last cell of the table", () => {
    const doc = "| A | B |\n|---|---|\n| 1 | 2 |"
    const state = mdState(doc, doc.length - 2) // inside cell '2'
    const spec = tableNextCellSpec(state)
    expect(spec).not.toBeNull()
    const next = apply(state, spec!)
    expect(next.doc.toString()).toBe("| A | B |\n|---|---|\n| 1 | 2 |\n|   |   |")
  })
})

describe("tablePrevCellSpec (Shift-Tab in tables)", () => {
  it("moves to the previous cell in the same row", () => {
    const doc = "| Col A | Col B |"
    const state = mdState(doc, 10) // inside Col B
    const spec = tablePrevCellSpec(state)
    expect(spec).not.toBeNull()
    const next = apply(state, spec!)
    expect(next.selection.main.anchor).toBe(2) // inside Col A
  })

  it("moves to the previous row skipping the separator row", () => {
    const doc = "| Col A | Col B |\n|---|---|\n| 1 | 2 |"
    const state = mdState(doc, doc.length - 6) // inside cell '1'
    const spec = tablePrevCellSpec(state)
    expect(spec).not.toBeNull()
    const next = apply(state, spec!)
    expect(next.doc.lineAt(next.selection.main.anchor).text).toBe("| Col A | Col B |")
  })
})

describe("insertBlockBreakSpec (Mod-Enter escape)", () => {
  it("escapes past a multi-line block inserting a new line", () => {
    const doc = "$$\nE = mc^2\n$$"
    const state = mdState(doc, 5) // inside LaTeX formula
    const spec = insertBlockBreakSpec(state)
    expect(spec).not.toBeNull()
    const next = apply(state, spec!)
    expect(next.doc.toString()).toBe("$$\nE = mc^2\n$$\n\n")
    expect(next.selection.main.anchor).toBe(next.doc.length)
  })
})


