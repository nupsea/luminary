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

import { useState } from "react"
import { createRoot, type Root } from "react-dom/client"
import { syntaxTree } from "@codemirror/language"
import { StateField, type EditorState, type Extension, type Range } from "@codemirror/state"
import { Decoration, EditorView, WidgetType, keymap, type DecorationSet } from "@codemirror/view"
import { Check, ChevronDown, ChevronUp, Copy, Pencil, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { type ExcalidrawNoteDiagramRef } from "@/lib/noteDiagrams"
import { moveBlockOrLineSpec } from "./markdownEditorCommands"

import {
  caretInTableRow,
  clickedSourceLine,
  firstEditableLine,
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
const tableLine = Decoration.line({ class: "cm-md-table-line" })
const mathLine = Decoration.line({ class: "cm-md-math-line" })

/** The sidecar an excalidraw diagram is paired with; the renderer needs both. */
const EXCALIDRAW_COMMENT = /^<!-- luminary:excalidraw=.+ -->$/

export interface LiveMarkdownOptions {
  /** Gives a rendered diagram the same edit button the preview has. */
  onEditDiagram?: (diagram: ExcalidrawNoteDiagramRef) => void
}

// eslint-disable-next-line react-refresh/only-export-components
function RenderedBlockContent({
  source,
  delimited,
  view,
  host,
  onEditDiagram,
}: {
  source: string
  delimited: boolean
  view: EditorView
  host: HTMLElement
  onEditDiagram?: (diagram: ExcalidrawNoteDiagramRef) => void
}) {
  const [copied, setCopied] = useState(false)

  const handleMove = (dir: -1 | 1) => {
    const from = view.posAtDOM(host)
    // Anchor at the target block to ensure correct block movement even if editor was focused elsewhere
    const stateWithPos = view.state.update({ selection: { anchor: from } }).state
    const spec = moveBlockOrLineSpec(stateWithPos, dir)
    if (spec) {
      view.dispatch(spec)
      view.focus()
    }
  }

  const handleEdit = () => {
    const from = view.posAtDOM(host)
    const firstLine = view.state.doc.lineAt(from)
    const offset = firstEditableLine(delimited)
    const line = view.state.doc.line(Math.min(firstLine.number + offset, view.state.doc.lines))
    view.dispatch({ selection: { anchor: line.to } })
    view.focus()
  }

  const handleCopy = () => {
    void navigator.clipboard.writeText(source)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
    toast.success("Block markdown copied")
  }

  const handleDelete = () => {
    const from = view.posAtDOM(host)
    const firstLine = view.state.doc.lineAt(from)
    const lines = source.split("\n").length
    const endLine = view.state.doc.line(Math.min(firstLine.number + lines - 1, view.state.doc.lines))
    let deleteTo = endLine.to
    if (endLine.number < view.state.doc.lines && view.state.doc.line(endLine.number + 1).text.trim() === "") {
      deleteTo = view.state.doc.line(endLine.number + 1).to
    }
    view.dispatch({ changes: { from: firstLine.from, to: deleteTo, insert: "" } })
    view.focus()
  }

  return (
    <div className="relative">
      <div
        className="absolute -top-3 right-2 z-20 flex items-center gap-0.5 rounded-md border border-border/80 bg-background/95 px-1 py-0.5 shadow-sm backdrop-blur-sm opacity-0 transition-opacity duration-150 group-hover/md-block:opacity-100 not-prose"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          onClick={() => handleMove(-1)}
          className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          title="Move block up (Alt+Up)"
        >
          <ChevronUp size={13} />
        </button>
        <button
          type="button"
          onClick={() => handleMove(1)}
          className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          title="Move block down (Alt+Down)"
        >
          <ChevronDown size={13} />
        </button>
        <div className="mx-0.5 h-3 w-px bg-border" />
        <button
          type="button"
          onClick={handleEdit}
          className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          title="Edit markdown source"
        >
          <Pencil size={12} />
        </button>
        <button
          type="button"
          onClick={handleCopy}
          className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          title="Copy markdown"
        >
          {copied ? <Check size={12} className="text-green-500" /> : <Copy size={12} />}
        </button>
        <button
          type="button"
          onClick={handleDelete}
          className="rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-colors"
          title="Delete block"
        >
          <Trash2 size={12} />
        </button>
      </div>

      <MarkdownRenderer
        reading={false}
        className="[&_.prose]:my-0 [&_figure]:my-1.5 [&_img]:my-1"
        onEditExcalidrawDiagram={
          onEditDiagram &&
          ((diagram) => {
            const base = view.posAtDOM(host)
            onEditDiagram({ ...diagram, start: diagram.start + base, end: diagram.end + base })
          })
        }
      >
        {source}
      </MarkdownRenderer>
    </div>
  )
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
    host.className = "cm-md-block group/md-block relative my-1"
    this.root = createRoot(host)
    this.root.render(
      <RenderedBlockContent
        source={this.source}
        delimited={this.delimited}
        view={view}
        host={host}
        onEditDiagram={this.onEditDiagram}
      />,
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
    const rowIndex = row ? rows.indexOf(row as HTMLTableRowElement) : null
    const line = view.state.doc.line(
      Math.min(
        firstLine.number +
          clickedSourceLine(rowIndex, this.source.split("\n").length, this.delimited),
        view.state.doc.lines,
      ),
    )
    // Inside a table, the column matters as much as the row: the end of the
    // line is past the last pipe, which is not any cell.
    const cell = target?.closest("td, th")
    if (row && cell) {
      const index = [...row.children].indexOf(cell)
      if (index >= 0) return line.from + caretInTableRow(line.text, index)
    }
    return line.to
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

  const renderBlock = (from: number, to: number, delimited = false, alwaysRender = false) => {
    const range = blockRange(state, from, to)
    if (!alwaysRender && lineIsBeingEdited(selection, range.from, range.to)) return false
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

  for (const { from, to } of mathBlockRanges(state.doc.toString())) {
    if (!renderBlock(from, to, true)) {
      const first = state.doc.lineAt(from).number
      const last = state.doc.lineAt(to).number
      for (let n = first; n <= last; n++) {
        const line = state.doc.line(n)
        marks.push(mathLine.range(line.from))
      }
    }
  }

  syntaxTree(state).iterate({
    enter: (node) => {
      if (rendersAsBlock(node.name)) {
        if (!renderBlock(node.from, node.to, isDelimitedBlock(node.name))) {
          if (node.name === "Table") {
            const first = state.doc.lineAt(node.from).number
            const last = state.doc.lineAt(node.to).number
            for (let n = first; n <= last; n++) {
              const line = state.doc.line(n)
              marks.push(tableLine.range(line.from))
            }
          }
        }
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
        // A diagram is the image plus the sidecar comment beneath it.
        // Always keep images rendered so navigating past them does not collapse
        // a 600px image into a 20px line of raw text and throw the viewport.
        const imageLine = state.doc.lineAt(node.to)
        const next = imageLine.number < state.doc.lines ? state.doc.line(imageLine.number + 1) : null
        const to = next && EXCALIDRAW_COMMENT.test(next.text.trim()) ? next.to : node.to
        renderBlock(node.from, to, false, true)
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
  ".cm-md-block": { margin: "4px 0", position: "relative" },
  ".cm-md-block .prose": {
    margin: "0 !important",
    maxWidth: "none !important",
  },
  ".cm-md-block .prose > *": {
    marginTop: "0.25rem !important",
    marginBottom: "0.25rem !important",
  },
  ".cm-md-block figure": {
    margin: "0.35rem 0 !important",
  },
  ".cm-line": {
    lineHeight: "1.5",
  },
  ".cm-line:empty, .cm-line:has(> br:only-child)": {
    height: "0.85rem",
    lineHeight: "0.85rem",
  },
  ".cm-md-code": {
    fontFamily: "var(--font-mono)",
    fontSize: "0.92em",
    backgroundColor: "hsl(var(--muted) / 0.6)",
  },
  ".cm-md-fence": { color: "hsl(var(--muted-foreground))", opacity: "0.55" },
  ".cm-md-table-line": {
    fontFamily: "var(--font-mono)",
    fontSize: "0.90em",
    letterSpacing: "-0.01em",
    lineHeight: "1.5",
    backgroundColor: "hsl(var(--muted) / 0.25)",
    paddingLeft: "4px",
  },
  ".cm-md-math-line": {
    fontFamily: "var(--font-mono)",
    fontSize: "0.92em",
    backgroundColor: "hsl(var(--primary) / 0.05)",
    borderLeft: "2px solid hsl(var(--primary) / 0.5)",
    paddingLeft: "8px",
  },
  ".cm-md-block img": { maxWidth: "100%", height: "auto" },
  ".cm-md-block table": {
    width: "auto",
    minWidth: "min(100%, 320px)",
    maxWidth: "100%",
    borderCollapse: "collapse",
    margin: "4px 0",
    fontSize: "0.875rem",
    lineHeight: "1.35",
  },
  ".cm-md-block th": {
    padding: "5px 10px",
    backgroundColor: "hsl(var(--muted) / 0.6)",
    color: "hsl(var(--foreground))",
    fontWeight: "600",
    fontSize: "0.75rem",
    textTransform: "uppercase",
    letterSpacing: "0.04em",
    border: "1px solid hsl(var(--border))",
    textAlign: "left",
    whiteSpace: "nowrap",
  },
  ".cm-md-block td": {
    padding: "5px 10px",
    border: "1px solid hsl(var(--border))",
    color: "hsl(var(--foreground) / 0.9)",
    verticalAlign: "top",
  },
  ".cm-md-block tr:nth-child(even) td": {
    backgroundColor: "hsl(var(--muted) / 0.15)",
  },
  ".cm-md-block tr:hover td": {
    backgroundColor: "hsl(var(--accent) / 0.3)",
  },
})

// A state field, not a view plugin: CodeMirror refuses block decorations from
// a plugin, and a rendered table is a block.
/**
 * A replaced block is one position to CodeMirror, so vertical motion jumps the
 * whole thing -- a table could only be entered with the mouse. Down and up put
 * the caret on the block's first or last line of content instead, which is what
 * reveals it.
 */
function stepInto(view: EditorView, field: StateField<DecorationSet>, dir: 1 | -1): boolean {
  if (!view.state.selection.main.empty) return false
  const { doc } = view.state
  const head = view.state.selection.main.head
  const line = doc.lineAt(head)
  const target = line.number + dir
  if (target < 1 || target > doc.lines) return false
  const edge = doc.line(target)
  let anchor: number | null = null
  // Coming down, the line below is the block's first; coming up, it is the
  // block's last. Either way the decoration covers that point.
  view.state.field(field).between(edge.from, edge.from, (from, to, deco) => {
    const widget = deco.spec.widget
    if (!(widget instanceof RenderedBlock)) return
    if (isImageOnlyParagraph(widget.source)) {
      const blockLineFrom = doc.lineAt(from).number
      const blockLineTo = doc.lineAt(to).number
      const nextNum = dir === 1 ? blockLineTo + 1 : blockLineFrom - 1
      if (nextNum >= 1 && nextNum <= doc.lines) {
        anchor = dir === 1 ? doc.line(nextNum).from : doc.line(nextNum).to
      }
      return
    }
    const lines = widget.source.split("\n").length
    const offset =
      dir === 1
        ? firstEditableLine(widget.delimited)
        : clickedSourceLine(null, lines, widget.delimited)
    const targetLine = doc.line(Math.min(doc.lineAt(from).number + offset, doc.lines))
    if (targetLine.text.includes("|")) {
      const cellPos = caretInTableRow(targetLine.text, 0)
      anchor = targetLine.from + cellPos
    } else {
      anchor = targetLine.to
    }
  })
  if (anchor === null) return false
  view.dispatch({ selection: { anchor } })
  return true
}

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
  const field = liveField(options)
  return [
    field,
    keymap.of([
      { key: "ArrowDown", run: (view) => stepInto(view, field, 1) },
      { key: "ArrowUp", run: (view) => stepInto(view, field, -1) },
    ]),
    // Inline, so it beats the base theme's monospace rule whatever order the
    // two style modules are mounted in. Prose is what is being written here.
    EditorView.contentAttributes.of({ style: "font-family: var(--font-sans)" }),
    liveTheme,
  ]
}
