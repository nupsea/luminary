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
import { type ExcalidrawNoteDiagramRef } from "@/lib/noteDiagrams"

import {
  clickedSourceLine,
  hidesBlock,
  hidesMark,
  isDelimitedBlock,
  isImageOnlyParagraph,
  lineIsBeingEdited,
  mathBlockRanges,
  rendersAsBlock,
  type TextRange,
} from "./liveMarkdownRules"

const hiddenMark = Decoration.replace({})
const hiddenBlock = Decoration.replace({ block: true })
const quoteLine = Decoration.line({ class: "cm-md-quote" })
const codeLine = Decoration.line({ class: "cm-md-code" })
const fenceLine = Decoration.line({ class: "cm-md-fence" })

/** The sidecar an excalidraw diagram is paired with; the renderer needs both. */
const EXCALIDRAW_COMMENT = /^<!-- luminary:excalidraw=.+ -->$/

export interface LiveMarkdownOptions {
  /** Gives a rendered diagram the same edit button the preview has. */
  onEditDiagram?: (diagram: ExcalidrawNoteDiagramRef) => void
}

class RenderedBlock extends WidgetType {
  private root: Root | null = null
  readonly source: string
  readonly delimited: boolean
  private readonly onEditDiagram?: (diagram: ExcalidrawNoteDiagramRef) => void

  constructor(
    source: string,
    delimited: boolean,
    onEditDiagram?: (diagram: ExcalidrawNoteDiagramRef) => void,
  ) {
    super()
    this.source = source
    this.delimited = delimited
    this.onEditDiagram = onEditDiagram
  }

  eq(other: RenderedBlock) {
    return other.source === this.source && other.delimited === this.delimited
  }

  toDOM(view: EditorView) {
    const host = document.createElement("div")
    host.className = "cm-md-block"
    this.root = createRoot(host)
    const edit = this.onEditDiagram
    this.root.render(
      <MarkdownRenderer
        reading
        onEditExcalidrawDiagram={
          edit &&
          ((diagram) => {
            // The renderer measured the diagram inside this block; the note it
            // is written back to is the whole document.
            const base = view.posAtDOM(host)
            edit({ ...diagram, start: diagram.start + base, end: diagram.end + base })
          })
        }
      >
        {this.source}
      </MarkdownRenderer>,
    )
    // The renderer paints after this returns, and an image finishes later
    // still, so the height CodeMirror measured here is always the wrong one.
    const observer = new ResizeObserver(() => view.requestMeasure())
    observer.observe(host)
    // Clicking a rendered block is how its source comes back, and the caret has
    // to land on the line that was clicked: at the block's start instead, the
    // first keystroke goes in front of the block and destroys it.
    host.addEventListener("mousedown", (event) => {
      const target = event.target as HTMLElement | null
      if (target?.closest("button, a")) return
      event.preventDefault()
      const anchor = this.caretFor(view, host, event, target)
      if (anchor !== null) view.dispatch({ selection: { anchor } })
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

  /**
   * Where the caret goes when this block is clicked. Code answers to the
   * character under the pointer -- the rendering preserves the source text, so
   * the offset into it is the offset into the block's body. Everything else
   * answers by line.
   */
  private caretFor(
    view: EditorView,
    host: HTMLElement,
    event: MouseEvent,
    target: HTMLElement | null,
  ): number | null {
    const from = view.posAtDOM(host)
    const firstLine = view.state.doc.lineAt(from)
    const code = target?.closest("pre")?.querySelector("code")
    if (code) {
      const offset = offsetInCode(code, event)
      if (offset !== null) {
        return Math.min(firstLine.to + 1 + offset, from + this.source.length)
      }
    }
    const rows = [...host.querySelectorAll("tr")]
    const row = target?.closest("tr")
    const line = clickedSourceLine(
      row ? rows.indexOf(row as HTMLTableRowElement) : null,
      this.source.split("\n").length,
      this.delimited,
    )
    return view.state.doc.line(Math.min(firstLine.number + line, view.state.doc.lines)).to
  }
}

/** Character offset of a click within a rendered code body, or null. */
function offsetInCode(code: Element, event: MouseEvent): number | null {
  const caret = document.caretRangeFromPoint?.(event.clientX, event.clientY)
  if (!caret || !code.contains(caret.startContainer)) return null
  const walker = document.createTreeWalker(code, NodeFilter.SHOW_TEXT)
  let offset = 0
  let node = walker.nextNode()
  while (node) {
    if (node === caret.startContainer) return offset + caret.startOffset
    offset += node.textContent?.length ?? 0
    node = walker.nextNode()
  }
  return null
}

function blockRange(state: EditorState, from: number, to: number): TextRange {
  return { from: state.doc.lineAt(from).from, to: state.doc.lineAt(to).to }
}

function decorate(state: EditorState, options: LiveMarkdownOptions): DecorationSet {
  const selection = state.selection.ranges
  const marks: Range<Decoration>[] = []
  const rendered: TextRange[] = []

  const renderBlock = (from: number, to: number, delimited = false) => {
    const range = blockRange(state, from, to)
    if (lineIsBeingEdited(selection, range.from, range.to)) return false
    rendered.push(range)
    marks.push(
      Decoration.replace({
        block: true,
        widget: new RenderedBlock(
          state.doc.sliceString(range.from, range.to),
          delimited,
          options.onEditDiagram,
        ),
      }).range(range.from, range.to),
    )
    return true
  }

  for (const { from, to } of mathBlockRanges(state.doc.toString())) renderBlock(from, to, true)

  syntaxTree(state).iterate({
    enter: (node) => {
      if (rendersAsBlock(node.name)) {
        renderBlock(node.from, node.to, isDelimitedBlock(node.name))
        return false
      }
      if (node.name === "FencedCode" && !renderBlock(node.from, node.to, true)) {
        // Being edited: still dressed as code, so revealing the source is not
        // a change of mode.
        const first = state.doc.lineAt(node.from).number
        const last = state.doc.lineAt(node.to).number
        for (let n = first; n <= last; n++) {
          const line = state.doc.line(n)
          marks.push(codeLine.range(line.from))
          if (n === first || n === last) marks.push(fenceLine.range(line.from))
        }
        return false
      }
      if (hidesBlock(node.name)) {
        const range = blockRange(state, node.from, node.to)
        if (rendered.some((r) => range.from >= r.from && range.to <= r.to)) return false
        if (lineIsBeingEdited(selection, range.from, range.to)) return false
        rendered.push(range)
        marks.push(hiddenBlock.range(range.from, range.to))
        return false
      }
      if (node.name === "Paragraph" && isImageOnlyParagraph(state.doc.sliceString(node.from, node.to))) {
        // A diagram is the image plus the sidecar comment beneath it. Rendered
        // apart, the renderer sees an image and offers no way to edit the scene.
        const imageLine = state.doc.lineAt(node.to)
        const next = imageLine.number < state.doc.lines ? state.doc.line(imageLine.number + 1) : null
        const to = next && EXCALIDRAW_COMMENT.test(next.text.trim()) ? next.to : node.to
        renderBlock(node.from, to)
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
  ".cm-md-code": {
    fontFamily: "var(--font-mono)",
    fontSize: "0.92em",
    backgroundColor: "hsl(var(--muted) / 0.6)",
  },
  ".cm-md-fence": { color: "hsl(var(--muted-foreground))", opacity: "0.55" },
  ".cm-md-block img": { maxWidth: "100%", height: "auto" },
  ".cm-md-block table": { fontSize: "0.9em" },
})

// A state field, not a view plugin: CodeMirror refuses block decorations from
// a plugin, and a rendered table is a block.
function liveField(options: LiveMarkdownOptions) {
  return StateField.define<DecorationSet>({
    create: (state) => decorate(state, options),
    update(value, tr) {
      if (!tr.docChanged && tr.state.selection.eq(tr.startState.selection)) return value
      return decorate(tr.state, options)
    },
    provide: (field) => EditorView.decorations.from(field),
  })
}

export function liveMarkdown(options: LiveMarkdownOptions = {}): Extension {
  return [
    liveField(options),
    // Inline, so it beats the base theme's monospace rule whatever order the
    // two style modules are mounted in. Prose is what is being written here.
    EditorView.contentAttributes.of({ style: "font-family: var(--font-sans)" }),
    liveTheme,
  ]
}
