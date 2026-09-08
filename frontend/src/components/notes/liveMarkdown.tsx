/**
 * Live markdown: the editor renders as it is written, for a surface with no
 * room for a preview beside it.
 *
 * Inline markers hide on every line but the one the cursor is on. Blocks --
 * code, tables, images, math -- are drawn by `MarkdownRenderer`, the same
 * component the preview uses, so the editor and the preview cannot disagree
 * about what a note looks like. Putting the cursor in a block gives its source
 * back.
 */

import { createRoot, type Root } from "react-dom/client"
import { syntaxTree } from "@codemirror/language"
import { StateField, type EditorState, type Extension, type Range } from "@codemirror/state"
import { Decoration, EditorView, WidgetType, type DecorationSet } from "@codemirror/view"

import { MarkdownRenderer } from "@/components/MarkdownRenderer"

import {
  hidesBlock,
  hidesMark,
  isImageOnlyParagraph,
  lineIsBeingEdited,
  mathBlockRanges,
  rendersAsBlock,
  type TextRange,
} from "./liveMarkdownRules"

const hiddenMark = Decoration.replace({})
const hiddenBlock = Decoration.replace({ block: true })
const quoteLine = Decoration.line({ class: "cm-md-quote" })

class RenderedBlock extends WidgetType {
  private root: Root | null = null
  readonly source: string

  constructor(source: string) {
    super()
    this.source = source
  }

  eq(other: RenderedBlock) {
    return other.source === this.source
  }

  toDOM(view: EditorView) {
    const host = document.createElement("div")
    host.className = "cm-md-block"
    this.root = createRoot(host)
    this.root.render(<MarkdownRenderer reading>{this.source}</MarkdownRenderer>)
    // The renderer paints after this returns, and an image finishes later
    // still, so the height CodeMirror measured here is always the wrong one.
    const observer = new ResizeObserver(() => view.requestMeasure())
    observer.observe(host)
    // Clicking a rendered block is how its source comes back. The editor maps
    // a click inside a replaced block to nothing on its own, so the position
    // is asked for and the selection put there.
    host.addEventListener("mousedown", (event) => {
      event.preventDefault()
      const pos = view.posAtDOM(host)
      view.dispatch({ selection: { anchor: pos } })
      view.focus()
    })
    return host
  }

  destroy() {
    const root = this.root
    this.root = null
    // Unmounting inside CodeMirror's update would unmount a React tree while
    // React is rendering.
    if (root) queueMicrotask(() => root.unmount())
  }

  ignoreEvent() {
    // The widget handles its own mousedown; the editor stays out of it.
    return true
  }
}

function blockRange(state: EditorState, from: number, to: number): TextRange {
  return { from: state.doc.lineAt(from).from, to: state.doc.lineAt(to).to }
}

function decorate(state: EditorState): DecorationSet {
  const selection = state.selection.ranges
  const marks: Range<Decoration>[] = []
  const rendered: TextRange[] = []

  const renderBlock = (from: number, to: number) => {
    const range = blockRange(state, from, to)
    if (lineIsBeingEdited(selection, range.from, range.to)) return
    rendered.push(range)
    marks.push(
      Decoration.replace({
        block: true,
        widget: new RenderedBlock(state.doc.sliceString(range.from, range.to)),
      }).range(range.from, range.to),
    )
  }

  for (const { from, to } of mathBlockRanges(state.doc.toString())) renderBlock(from, to)

  syntaxTree(state).iterate({
    enter: (node) => {
      if (rendersAsBlock(node.name)) {
        renderBlock(node.from, node.to)
        return false
      }
      if (hidesBlock(node.name)) {
        const range = blockRange(state, node.from, node.to)
        if (lineIsBeingEdited(selection, range.from, range.to)) return false
        rendered.push(range)
        marks.push(hiddenBlock.range(range.from, range.to))
        return false
      }
      if (node.name === "Paragraph" && isImageOnlyParagraph(state.doc.sliceString(node.from, node.to))) {
        renderBlock(node.from, node.to)
        return false
      }
      if (node.name === "Blockquote") {
        for (let pos = node.from; pos <= node.to; ) {
          const line = state.doc.lineAt(pos)
          marks.push(quoteLine.range(line.from))
          pos = line.to + 1
        }
        return
      }
      if (!hidesMark(node.name, node.node.parent?.name)) return
      if (rendered.some((r) => node.from >= r.from && node.to <= r.to)) return
      const line = state.doc.lineAt(node.from)
      if (lineIsBeingEdited(selection, line.from, line.to)) return
      // The space after `###` or `>` belongs to the marker: left behind it
      // indents the text it was marking.
      let end = node.to
      if (
        (node.name === "HeaderMark" || node.name === "QuoteMark") &&
        state.doc.sliceString(end, end + 1) === " "
      ) {
        end += 1
      }
      if (end > node.from) marks.push(hiddenMark.range(node.from, end))
    },
  })

  return Decoration.set(marks, true)
}

const liveTheme = EditorView.theme({
  ".cm-md-quote": {
    borderLeft: "2px solid hsl(var(--border))",
    paddingLeft: "10px",
    color: "hsl(var(--muted-foreground))",
  },
  ".cm-md-block": { margin: "4px 0" },
  ".cm-md-block img": { maxWidth: "100%", height: "auto" },
  ".cm-md-block table": { fontSize: "0.9em" },
})

// A state field, not a view plugin: CodeMirror refuses block decorations from
// a plugin, and a rendered table is a block.
const liveField = StateField.define<DecorationSet>({
  create: (state) => decorate(state),
  update(value, tr) {
    if (!tr.docChanged && tr.state.selection.eq(tr.startState.selection)) return value
    return decorate(tr.state)
  },
  provide: (field) => EditorView.decorations.from(field),
})

export function liveMarkdown(): Extension {
  return [
    liveField,
    // Inline, so it beats the base theme's monospace rule whatever order the
    // two style modules are mounted in. Prose is what is being written here.
    EditorView.contentAttributes.of({ style: "font-family: var(--font-sans)" }),
    liveTheme,
  ]
}
