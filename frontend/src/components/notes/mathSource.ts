/**
 * Where a note's math is, and how its source looks while it is source: in the
 * split view's editor, and on the line the live editor has given back.
 */

import { syntaxTree } from "@codemirror/language"
import { StateField, type EditorState, type Extension, type Range } from "@codemirror/state"
import { Decoration, EditorView, type DecorationSet } from "@codemirror/view"

import { hidesBlock, inlineMathRanges, mathBlockRanges, type TextRange } from "./liveMarkdownRules"

const overlaps = (a: TextRange, b: TextRange) => a.from <= b.to && a.to >= b.from

/** Display and inline math, outside code; inline math also outside tables and HTML blocks. */
export function mathRanges(state: EditorState): { display: TextRange[]; inline: TextRange[] } {
  const code: TextRange[] = []
  const opaque: TextRange[] = []
  syntaxTree(state).iterate({
    enter: (node) => {
      const range = { from: node.from, to: node.to }
      if (node.name === "FencedCode" || node.name === "CodeBlock") code.push(range)
      else if (node.name === "Table" || hidesBlock(node.name)) opaque.push(range)
      else return
      return false
    },
  })
  const display = mathBlockRanges(state.doc.toString()).filter((d) => !code.some((c) => overlaps(c, d)))
  const skip = [...code, ...opaque, ...display]
  const inline: TextRange[] = []
  for (let n = 1; n <= state.doc.lines; n++) {
    const line = state.doc.line(n)
    if (skip.some((r) => overlaps(r, line))) continue
    for (const r of inlineMathRanges(line.text)) inline.push({ from: line.from + r.from, to: line.from + r.to })
  }
  return { display, inline }
}

const mathLine = Decoration.line({ class: "cm-md-math-line" })
const inlineSource = Decoration.mark({ class: "cm-md-math-src" })

function decorate(state: EditorState): DecorationSet {
  const { display, inline } = mathRanges(state)
  const marks: Range<Decoration>[] = []
  for (const { from, to } of display) {
    for (let n = state.doc.lineAt(from).number; n <= state.doc.lineAt(to).number; n++) {
      marks.push(mathLine.range(state.doc.line(n).from))
    }
  }
  for (const { from, to } of inline) marks.push(inlineSource.range(from, to))
  return Decoration.set(marks, true)
}

const mathSourceField = StateField.define<DecorationSet>({
  create: decorate,
  update(deco, tr) {
    // The parser finishes in the background; a code block it reaches late
    // stops what is inside it being math.
    return tr.docChanged || syntaxTree(tr.startState) !== syntaxTree(tr.state) ? decorate(tr.state) : deco
  },
  provide: (f) => EditorView.decorations.from(f),
})

const mathSourceTheme = EditorView.baseTheme({
  ".cm-md-math-line": {
    fontFamily: "var(--font-mono)",
    fontSize: "0.95em",
    backgroundColor: "hsl(var(--primary) / 0.05)",
    borderLeft: "2px solid hsl(var(--primary) / 0.5)",
    paddingLeft: "8px",
  },
  ".cm-md-math-src": {
    fontFamily: "var(--font-mono)",
    fontSize: "0.92em",
    color: "hsl(var(--primary))",
    backgroundColor: "hsl(var(--primary) / 0.06)",
    borderRadius: "3px",
  },
})

export function mathSource(): Extension {
  return [mathSourceField, mathSourceTheme]
}
