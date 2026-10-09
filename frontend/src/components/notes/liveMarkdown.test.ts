import { describe, expect, it } from "vitest"
import React from "react"
import ReactDOMServer from "react-dom/server"
import { EditorState } from "@codemirror/state"
import { markdown, markdownLanguage } from "@codemirror/lang-markdown"
import { defaultKeymap } from "@codemirror/commands"
import { keymap } from "@codemirror/view"
import { liveMarkdown } from "./liveMarkdown"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"

const sampleTableDoc = `
# 2 DO table
| # | Description | Status |
| --- | --- | -- |
| 1 | Retrieval Failure attributed to Routing Failure | In Progress |
| 2 | Run /ultrareview for a cloud-based multi-agent review that finds and verifies bugs in your branch — 3 free reviews left| -- |
| 3 | Review the above with Gemini flash | -- |
| 4 | Note editor with key board shortcuts acts crazy. | -- |
| 5 | --- | -- |
| 6 | --- | -- |

$$
fb = f + b
$$

![Diagram|large](__LUMINARY_IMG__/notes/0ff71a3f-a7d2-4181-a6ed-da44ccf070e7.svg)
<!-- luminary:excalidraw=__LUMINARY_IMG__/notes/8a640b0c-2c83-4a6c-9442-310be73bf7a3.excalidraw.json -->
`

describe("liveMarkdown decorations", () => {
  it("creates block widgets for tables, math, and diagrams without editing selection", () => {
    const state = EditorState.create({
      doc: sampleTableDoc,
      selection: { anchor: 0 },
      extensions: [markdown({ base: markdownLanguage }), liveMarkdown()],
    })

    // Find decoration set
    // @ts-expect-error private field access for test assertion
    const fields = state.values as unknown[]
    interface DecoRange {
      spec?: { widget?: { source: string } }
    }
    interface TestDecoSet {
      size: number
      between: (from: number, to: number, f: (from: number, to: number, deco: DecoRange) => void) => void
    }
    const decoSets = fields.filter((val): val is TestDecoSet =>
      Boolean(val && typeof val === "object" && "size" in val && typeof (val as { size: unknown }).size === "number" && (val as { size: number }).size > 0),
    )
    expect(decoSets.length).toBeGreaterThan(0)

    const widgets: string[] = []
    decoSets[0].between(0, state.doc.length, (_from, _to, deco) => {
      if (deco.spec?.widget) {
        widgets.push(deco.spec.widget.source)
      }
    })

    expect(widgets.length).toBe(3)
    expect(widgets[0]).toContain("| # | Description | Status |")
    expect(widgets[1]).toContain("fb = f + b")
    expect(widgets[2]).toContain("![Diagram|large]")
  })

  it("renders a standalone pasted image as a block widget", () => {
    const doc = `## Heading

Some text

$$
x = y + z
$$

![Pasted Image|medium](__LUMINARY_IMG__/notes/4b5f7f44-0389-4da9-a1fe-adb4c92fc1b0.png)
`
    const state = EditorState.create({
      doc,
      selection: { anchor: doc.length },
      extensions: [markdown({ base: markdownLanguage }), liveMarkdown()],
    })

    // Find decoration set
    // @ts-expect-error private field access for test assertion
    const fields = state.values as unknown[]
    interface DecoRange {
      spec?: { widget?: { source: string } }
    }
    interface TestDecoSet {
      size: number
      between: (from: number, to: number, f: (from: number, to: number, deco: DecoRange) => void) => void
    }
    const decoSets = fields.filter((val): val is TestDecoSet =>
      Boolean(val && typeof val === "object" && "size" in val && typeof (val as { size: unknown }).size === "number" && (val as { size: number }).size > 0),
    )

    const widgets: string[] = []
    for (const ds of decoSets) {
      ds.between(0, state.doc.length, (_from, _to, deco) => {
        if (deco.spec?.widget) {
          widgets.push(deco.spec.widget.source)
        }
      })
    }
    expect(widgets.some((w) => w.includes("Pasted Image"))).toBe(true)
  })

  it("renders an image immediately following a math block without blank lines as a block widget", () => {
    const doc = `$$
x = y + z
$$
![Pasted Image|medium](__LUMINARY_IMG__/notes/4b5f7f44-0389-4da9-a1fe-adb4c92fc1b0.png)
`
    const state = EditorState.create({
      doc,
      selection: { anchor: doc.length },
      extensions: [markdown({ base: markdownLanguage }), liveMarkdown()],
    })

    // @ts-expect-error private field access for test assertion
    const fields = state.values as unknown[]
    interface DecoRange {
      spec?: { widget?: { source: string } }
    }
    interface TestDecoSet {
      size: number
      between: (from: number, to: number, f: (from: number, to: number, deco: DecoRange) => void) => void
    }
    const decoSets = fields.filter((val): val is TestDecoSet =>
      Boolean(val && typeof val === "object" && "size" in val && typeof (val as { size: unknown }).size === "number" && (val as { size: number }).size > 0),
    )

    const widgets: string[] = []
    for (const ds of decoSets) {
      ds.between(0, state.doc.length, (_from, _to, deco) => {
        if (deco.spec?.widget) {
          widgets.push(deco.spec.widget.source)
        }
      })
    }
    expect(widgets.some((w) => w.includes("Pasted Image"))).toBe(true)
  })

  it("unrenders image into editable markdown source when cursor is placed inside the line to edit", () => {
    const doc = "![Pasted Image|medium](__LUMINARY_IMG__/notes/4b5f7f44-0389-4da9-a1fe-adb4c92fc1b0.png)\n"
    // Place cursor inside the image line (e.g. at position 10, inside the alt text)
    const state = EditorState.create({
      doc,
      selection: { anchor: 10 },
      extensions: [markdown({ base: markdownLanguage }), liveMarkdown()],
    })

    // @ts-expect-error private field access for test assertion
    const fields = state.values as unknown[]
    interface DecoRange {
      spec?: { widget?: { source: string } }
    }
    interface TestDecoSet {
      size: number
      between: (from: number, to: number, f: (from: number, to: number, deco: DecoRange) => void) => void
    }
    const decoSets = fields.filter((val): val is TestDecoSet =>
      Boolean(val && typeof val === "object" && "size" in val && typeof (val as { size: unknown }).size === "number" && (val as { size: number }).size > 0),
    )

    const widgets: string[] = []
    for (const ds of decoSets) {
      ds.between(0, state.doc.length, (_from, _to, deco) => {
        if (deco.spec?.widget) {
          widgets.push(deco.spec.widget.source)
        }
      })
    }
    // Block widget should NOT be rendered because user is editing the source
    expect(widgets.some((w) => w.includes("Pasted Image"))).toBe(false)
  })

  it("keeps image rendered as widget when the entire image line is selected as a block unit", () => {
    const doc = "![Pasted Image|medium](__LUMINARY_IMG__/notes/4b5f7f44-0389-4da9-a1fe-adb4c92fc1b0.png)\n"
    const lineEnd = doc.indexOf("\n")
    const state = EditorState.create({
      doc,
      selection: { anchor: 0, head: lineEnd },
      extensions: [markdown({ base: markdownLanguage }), liveMarkdown()],
    })

    // @ts-expect-error private field access for test assertion
    const fields = state.values as unknown[]
    interface DecoRange {
      spec?: { widget?: { source: string } }
    }
    interface TestDecoSet {
      size: number
      between: (from: number, to: number, f: (from: number, to: number, deco: DecoRange) => void) => void
    }
    const decoSets = fields.filter((val): val is TestDecoSet =>
      Boolean(val && typeof val === "object" && "size" in val && typeof (val as { size: unknown }).size === "number" && (val as { size: number }).size > 0),
    )

    const widgets: string[] = []
    for (const ds of decoSets) {
      ds.between(0, state.doc.length, (_from, _to, deco) => {
        if (deco.spec?.widget) {
          widgets.push(deco.spec.widget.source)
        }
      })
    }
    // Block widget SHOULD be rendered with selection
    expect(widgets.some((w) => w.includes("Pasted Image"))).toBe(true)
  })
})

describe("MarkdownRenderer table whitespace", () => {
  it("does not produce foster-parented leading newlines before rendered tables", () => {
    const tableText = `| # | Description | Status |
| --- | --- | -- |
| 1 | Test item | In Progress |
| 2 | Second item | Done |`

    const html = ReactDOMServer.renderToStaticMarkup(
      React.createElement(MarkdownRenderer, { reading: false, children: tableText }),
    )

    // Verify there are no leading newlines before the table
    const leadingNewlinesMatch = html.match(/>(\s*)<table/)
    if (leadingNewlinesMatch) {
      expect(leadingNewlinesMatch[1]).not.toContain("\n\n")
    }
    expect(html).toContain("<table")
    expect(html).toContain("Test item")
  })
})

describe("DEFAULT_NOTE_FONT_SIZE constant", () => {
  it("is calibrated to standard 14px", async () => {
    const { DEFAULT_NOTE_FONT_SIZE } = await import("./MarkdownCodeEditor")
    expect(DEFAULT_NOTE_FONT_SIZE).toBe(14)
  })
})

describe("liveMarkdown ArrowUp and ArrowDown vertical navigation", () => {
  it("navigates line-by-line without jumping over code blocks or math blocks", async () => {
    const { stepInto, liveField } = await import("./liveMarkdown")
    const doc = `| C1 | C2 |
| --- | --- |
| x | y |

\`\`\`python
import time

s = time.start()
\`\`\`

$$
x = y + z
$$

The size of the problem is usually straightforward.`

    const prosePos = doc.indexOf("The size of the problem")
    const field = liveField({})
    let state = EditorState.create({
      doc,
      selection: { anchor: prosePos },
      extensions: [markdown({ base: markdownLanguage }), field],
    })

    const createMockView = () => ({
      state,
      dispatch: (tr: { selection?: { anchor: number } }) => {
        state = state.update(tr).state
      },
    })

    // 1st ArrowUp: should land on the blank line immediately above prose, NOT jumping to table!
    const mockView1 = createMockView()
    // @ts-expect-error test mock
    const handled1 = stepInto(mockView1, field, -1)
    expect(handled1).toBe(true)
    const lineAfter1 = state.doc.lineAt(state.selection.main.head)
    const blankLineAboveProse = doc.slice(0, prosePos).lastIndexOf("\n")
    expect(lineAfter1.from).toBe(blankLineAboveProse)
    expect(lineAfter1.text.trim()).toBe("")

    // 2nd ArrowUp: should land inside the Math block (x = y + z)
    const mockView2 = createMockView()
    // @ts-expect-error test mock
    const handled2 = stepInto(mockView2, field, -1)
    expect(handled2).toBe(true)
    const lineAfter2 = state.doc.lineAt(state.selection.main.head)
    expect(lineAfter2.text).toContain("x = y + z")

    // Move to blank line above Math block (between python block and math block)
    const blankLineAboveMath = doc.indexOf("```\n\n") + 4
    state = state.update({ selection: { anchor: blankLineAboveMath } }).state
    const mockView3 = createMockView()
    // 3rd ArrowUp: should land inside the Python code block (s = time.start())
    // @ts-expect-error test mock
    const handled3 = stepInto(mockView3, field, -1)
    expect(handled3).toBe(true)
    const lineAfter3 = state.doc.lineAt(state.selection.main.head)
    expect(lineAfter3.text).toContain("s = time.start()")
  })

  it("traces stepInto with the user's exact note content", async () => {
    const { stepInto, liveField } = await import("./liveMarkdown")
    const doc = `## Data Structure

A data structure is what it says on the tin: a way to store information in an organized, structured manner. We’ll be creating data structures using C# arrays, classes, structs, records, and interfaces, as we’d expect.


| C1 | C2 |
| --- | --- |
| x | y |
| n | tdkfjd | 

\`\`\`python

import time

s = time.start()

\`\`\`

$$
x = y + z
$$



The size of the problem is usually straightforward.

![Pasted Image|medium](__LUMINARY_IMG__/notes/e95a1b0e-9a58-404d-8942-783d851ce879.png)



`
    const field = liveField({})
    let state = EditorState.create({
      doc,
      selection: { anchor: doc.indexOf("The size of the problem") },
      extensions: [markdown({ base: markdownLanguage }), field],
    })

    const view = {
      state,
      dispatch: (tr: { selection?: { anchor: number } }) => {
        state = state.update(tr).state
        view.state = state
      },
    }

    for (let i = 1; i <= 25; i++) {
      // @ts-expect-error test mock
      const handled = stepInto(view, field, -1)
      if (!handled) break
    }
    const finalLine = state.doc.lineAt(state.selection.main.head)
    expect(finalLine.number).toBe(1)
    expect(finalLine.text).toBe("## Data Structure")
  })

  it("collapses active selection cleanly on ArrowUp instead of skipping over blocks", async () => {
    const { stepInto, liveField } = await import("./liveMarkdown")
    const doc = `First line

Second line

![Pasted Image|medium](url)

Third line`

    const field = liveField({})
    const imagePos = doc.indexOf("![Pasted Image")
    // Select the whole image line (as happens when an image widget is clicked)
    let state = EditorState.create({
      doc,
      selection: { anchor: imagePos, head: imagePos + 27 },
      extensions: [markdown({ base: markdownLanguage }), field],
    })

    const view = {
      state,
      dispatch: (tr: { selection?: { anchor: number } }) => {
        state = state.update(tr).state
        view.state = state
      },
    }

    // Press ArrowUp while image is selected: should collapse and land on line above image (blank line)
    // @ts-expect-error test mock
    const handled = stepInto(view, field, -1)
    expect(handled).toBe(true)
    const lineAfter = state.doc.lineAt(state.selection.main.head)
    expect(lineAfter.text).toBe("")
    expect(lineAfter.number).toBe(4)
  })

  it("dynamically decorates bullet lists, task lists, and ordered lists", async () => {
    const { liveField } = await import("./liveMarkdown")
    const doc = `Prompts

1. In your own words
2. Maintain docs

List
- one
  - nested
- [ ] task 1
- [x] done 2`

    const field = liveField({})
    // Cursor at position 0 (not on lists)
    const state = EditorState.create({
      doc,
      selection: { anchor: 0 },
      extensions: [markdown({ base: markdownLanguage }), field],
    })

    // Inspect decorations
    // @ts-expect-error private field access
    const fields = state.values as unknown[]
    interface DecoRange {
      spec?: {
        widget?: { level?: number; checked?: boolean }
        class?: string
      }
    }
    interface TestDecoSet {
      size: number
      between: (from: number, to: number, f: (from: number, to: number, deco: DecoRange) => void) => void
    }
    const decoSets = fields.filter((val): val is TestDecoSet =>
      Boolean(val && typeof val === "object" && "size" in val && typeof (val as { size: unknown }).size === "number" && (val as { size: number }).size > 0),
    )
    expect(decoSets.length).toBeGreaterThan(0)

    const listLineDecos: string[] = []
    const bulletWidgets: number[] = []
    const taskWidgets: boolean[] = []

    decoSets[0].between(0, state.doc.length, (_from, _to, deco) => {
      if (deco.spec?.class?.includes("cm-md-list-line")) {
        listLineDecos.push(deco.spec.class)
      }
      if (deco.spec?.widget && typeof deco.spec.widget.level === "number") {
        bulletWidgets.push(deco.spec.widget.level)
      }
      if (deco.spec?.widget && typeof deco.spec.widget.checked === "boolean") {
        taskWidgets.push(deco.spec.widget.checked)
      }
    })

    // 6 list lines: 2 ordered + 2 bullet + 2 task
    expect(listLineDecos.length).toBe(6)
    expect(listLineDecos.some((c) => c.includes("cm-md-task-done"))).toBe(true)

    // Bullet widgets: level 0 for "- one", level 1 for "  - nested"
    expect(bulletWidgets).toEqual([0, 1])

    // Task widgets: false for "- [ ] task 1", true for "- [x] done 2"
    expect(taskWidgets).toEqual([false, true])
  })

  it("reveals raw list marker when cursor is placed on that list line", async () => {
    const { liveField } = await import("./liveMarkdown")
    const doc = `List\n- one\n- two`
    const field = liveField({})
    // Cursor on line 2 ("- one")
    const onePos = doc.indexOf("- one") + 2
    const state = EditorState.create({
      doc,
      selection: { anchor: onePos },
      extensions: [markdown({ base: markdownLanguage }), field],
    })

    // @ts-expect-error private field access
    const fields = state.values as unknown[]
    interface DecoRange {
      from?: number
      to?: number
      spec?: {
        widget?: { level?: number }
      }
    }
    interface TestDecoSet {
      size: number
      between: (from: number, to: number, f: (from: number, to: number, deco: DecoRange) => void) => void
    }
    const decoSets = fields.filter((val): val is TestDecoSet =>
      Boolean(val && typeof val === "object" && "size" in val && typeof (val as { size: unknown }).size === "number" && (val as { size: number }).size > 0),
    )

    const bulletWidgets: { from: number; to: number }[] = []
    decoSets[0].between(0, state.doc.length, (from, to, deco) => {
      if (deco.spec?.widget && typeof deco.spec.widget.level === "number") {
        bulletWidgets.push({ from, to })
      }
    })

    // Only line 3 ("- two") should have a bullet widget; line 2 ("- one") is revealed for editing!
    expect(bulletWidgets.length).toBe(1)
    const line3 = state.doc.line(3)
    expect(bulletWidgets[0].from).toBeGreaterThanOrEqual(line3.from)
  })
})

describe("live editor wiring", () => {
  // CodeMirror measures a block widget by its border box; a margin shifts every
  // click and arrow below the block (16px per diagram put clicks a line low).
  it("gives a rendered block no vertical margin", async () => {
    const { BLOCK_HOST_CLASS, liveThemeSpec } = await import("./liveMarkdown")
    expect(BLOCK_HOST_CLASS.split(/\s+/).filter((c) => /^-?m[ytb]?-/.test(c))).toEqual([])
    const hostRule = liveThemeSpec[".cm-md-block"] as Record<string, string>
    const margins = Object.entries(hostRule).filter(
      ([prop, value]) => /^margin(Top|Bottom)?$/.test(prop) && !/^0(px)?( 0(px)?)?$/.test(value),
    )
    expect(margins).toEqual([])
  })

  // The stepInto tests above call it directly; this guards that the mounted
  // editor's own ArrowUp/ArrowDown actually reach it.
  it("lets the live arrow bindings outrank CodeMirror's defaults", async () => {
    const { noteEditorKeymaps } = await import("./MarkdownCodeEditor")
    const state = EditorState.create({
      extensions: [markdown({ base: markdownLanguage }), ...noteEditorKeymaps({ current: {} }), liveMarkdown()],
    })
    const bindings = state.facet(keymap).flat()
    for (const key of ["ArrowUp", "ArrowDown"]) {
      const stock = defaultKeymap.find((b) => b.key === key)!.run
      expect(bindings.find((b) => b.key === key)!.run, key).not.toBe(stock)
    }
  })
})

