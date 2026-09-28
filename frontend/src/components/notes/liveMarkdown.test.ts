import { describe, expect, it } from "vitest"
import React from "react"
import ReactDOMServer from "react-dom/server"
import { EditorState } from "@codemirror/state"
import { markdown, markdownLanguage } from "@codemirror/lang-markdown"
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
})
