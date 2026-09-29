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
import { Prec, StateField, type EditorState, type Extension, type Range } from "@codemirror/state"
import { Decoration, EditorView, WidgetType, keymap, type DecorationSet } from "@codemirror/view"
import { Check, ChevronDown, ChevronUp, Copy, Pencil, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { type ExcalidrawNoteDiagramRef } from "@/lib/noteDiagrams"
import { moveBlockOrLineSpec, setImageSizeInMarkdown } from "./markdownEditorCommands"
import { API_BASE } from "@/lib/config"
import { cn } from "@/lib/utils"

import {
  caretInTableRow,
  clickedSourceLine,
  columnOffset,
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
  const from = view.posAtDOM(host)
  const firstLine = view.state.doc.lineAt(from)
  const lines = source.split("\n").length
  const endLine = view.state.doc.line(Math.min(firstLine.number + lines - 1, view.state.doc.lines))
  const isSelected =
    !view.state.selection.main.empty &&
    view.state.selection.main.from <= firstLine.from &&
    view.state.selection.main.to >= endLine.to

  const handleMove = (dir: -1 | 1) => {
    const blockPos = view.posAtDOM(host)
    // Anchor at the target block to ensure correct block movement even if editor was focused elsewhere
    const stateWithPos = view.state.update({ selection: { anchor: blockPos } }).state
    const spec = moveBlockOrLineSpec(stateWithPos, dir)
    if (spec) {
      view.dispatch(spec)
      view.focus()
    }
  }

  const handleEdit = () => {
    const blockPos = view.posAtDOM(host)
    const line = view.state.doc.lineAt(blockPos)
    if (isImageOnlyParagraph(source)) {
      view.dispatch({ selection: { anchor: Math.min(line.from + 2, line.to) } })
    } else {
      const offset = firstEditableLine(delimited)
      const targetLine = view.state.doc.line(Math.min(line.number + offset, view.state.doc.lines))
      view.dispatch({ selection: { anchor: targetLine.to } })
    }
    view.focus()
  }

  const handleCopy = () => {
    void navigator.clipboard.writeText(source)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
    toast.success("Block markdown copied")
  }

  const handleDelete = () => {
    const blockPos = view.posAtDOM(host)
    const startLine = view.state.doc.lineAt(blockPos)
    const lineCount = source.split("\n").length
    const lastLine = view.state.doc.line(Math.min(startLine.number + lineCount - 1, view.state.doc.lines))
    let deleteFrom = startLine.from
    let deleteTo = lastLine.to
    if (lastLine.number < view.state.doc.lines) {
      deleteTo = view.state.doc.line(lastLine.number + 1).from
    } else if (startLine.number > 1) {
      deleteFrom = view.state.doc.line(startLine.number - 1).to
    }
    view.dispatch({ changes: { from: deleteFrom, to: deleteTo, insert: "" } })
    view.focus()
  }

  return (
    <div
      className={cn(
        "relative rounded-lg transition-all duration-150",
        isSelected && "ring-2 ring-primary ring-offset-2 ring-offset-background",
      )}
    >
      <div
        className={cn(
          "absolute -top-3 right-2 z-20 flex items-center gap-0.5 rounded-md border border-border/80 bg-background/95 px-1 py-0.5 shadow-sm backdrop-blur-sm transition-opacity duration-150 not-prose",
          isSelected ? "opacity-100" : "opacity-0 group-hover/md-block:opacity-100",
        )}
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
        onSetImageSize={(src, size) => {
          const blockPos = view.posAtDOM(host)
          const startLine = view.state.doc.lineAt(blockPos)
          const lineCount = source.split("\n").length
          const lastLine = view.state.doc.line(Math.min(startLine.number + lineCount - 1, view.state.doc.lines))
          const newBlockText = setImageSizeInMarkdown(source, src, size, API_BASE)
          if (newBlockText !== source) {
            view.dispatch({ changes: { from: startLine.from, to: lastLine.to, insert: newBlockText } })
            view.focus()
          }
        }}
      >
        {source}
      </MarkdownRenderer>
    </div>
  )
}

class RenderedBlock extends WidgetType {
  private root: Root | null = null
  private endDrag: (() => void) | null = null
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
      if (target?.closest("button, a, input, select, textarea")) return

      const from = view.posAtDOM(host)
      const firstLine = view.state.doc.lineAt(from)
      const lines = this.source.split("\n").length
      const endLine = view.state.doc.line(Math.min(firstLine.number + lines - 1, view.state.doc.lines))

      // If clicking an image block: select the entire block as a unit so user can delete or navigate smoothly!
      if (isImageOnlyParagraph(this.source)) {
        event.preventDefault()
        view.focus()
        if (event.shiftKey) {
          view.dispatch({
            selection: { anchor: view.state.selection.main.anchor, head: endLine.to },
          })
          return
        }
        view.dispatch({
          selection: { anchor: firstLine.from, head: endLine.to },
        })
        return
      }

      event.preventDefault()
      const anchor = this.caretFor(view, host, event, target)
      if (anchor === null) return
      view.focus()
      if (event.shiftKey) {
        view.dispatch({ selection: { anchor: view.state.selection.main.anchor, head: anchor } })
        return
      }
      view.dispatch({ selection: { anchor } })
      this.startDrag(view, anchor)
    })

    host.addEventListener("dblclick", (event) => {
      const target = event.target as HTMLElement | null
      if (target?.closest("button, a, input, select, textarea")) return
      if (isImageOnlyParagraph(this.source)) {
        event.preventDefault()
        const from = view.posAtDOM(host)
        const firstLine = view.state.doc.lineAt(from)
        view.focus()
        view.dispatch({ selection: { anchor: Math.min(firstLine.from + 2, firstLine.to) } })
      }
    })
    return host
  }

  /**
   * `ignoreEvent` hides a drag that starts on a widget from CodeMirror's own
   * selection tracking; this replicates it. One dispatch per frame, as CodeMirror
   * does: faster dispatches outrun layout and draw the selection off the widget.
   */
  private startDrag(view: EditorView, anchor: number) {
    this.endDrag?.()
    let frame = 0
    let pending: { x: number; y: number } | null = null
    const flush = () => {
      frame = 0
      if (!pending) return
      const head = view.posAtCoords(pending)
      pending = null
      if (head !== null) view.dispatch({ selection: { anchor, head } })
    }
    const onMove = (event: MouseEvent) => {
      pending = { x: event.clientX, y: event.clientY }
      if (!frame) frame = requestAnimationFrame(flush)
    }
    const onUp = () => this.endDrag?.()
    window.addEventListener("mousemove", onMove)
    window.addEventListener("mouseup", onUp)
    this.endDrag = () => {
      cancelAnimationFrame(frame)
      window.removeEventListener("mousemove", onMove)
      window.removeEventListener("mouseup", onUp)
      this.endDrag = null
    }
  }

  updateDOM(dom: HTMLElement, view: EditorView): boolean {
    if (this.root) {
      this.root.render(
        <RenderedBlockContent
          source={this.source}
          delimited={this.delimited}
          view={view}
          host={dom}
          onEditDiagram={this.onEditDiagram}
        />,
      )
      return true
    }
    return false
  }

  destroy(dom: HTMLElement) {
    this.endDrag?.()
    const root = this.root
    this.root = null
    // Unmounting inside CodeMirror's update would unmount a React tree while
    // React is rendering. Only unmount when dom is truly disconnected.
    if (root) {
      queueMicrotask(() => {
        if (!dom.isConnected) root.unmount()
      })
    }
  }

  ignoreEvent(event: Event): boolean {
    const target = event.target as HTMLElement | null
    if (target?.closest("button, a, input, select, textarea")) return true
    return false
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
    const sourceLines = this.source.split("\n")
    const totalLines = sourceLines.length

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
    const cell = target?.closest("td, th")
    if (row && cell && rowIndex !== null) {
      const line = view.state.doc.line(
        Math.min(
          firstLine.number +
            clickedSourceLine(rowIndex, totalLines, this.delimited),
          view.state.doc.lines,
        ),
      )
      const index = [...row.children].indexOf(cell)
      if (index >= 0) return line.from + caretInTableRow(line.text, index)
      return line.to
    }

    // Spatial coordinate mapping for non-table blocks:
    // Maps click position to line and column within block instead of jumping to the bottom
    const rect = host.getBoundingClientRect()
    const relY = Math.max(0, event.clientY - rect.top)
    const fraction = relY / Math.max(rect.height, 1)

    let lineOffset = Math.floor(fraction * totalLines)
    lineOffset = Math.max(0, Math.min(lineOffset, totalLines - 1))
    if (this.delimited && totalLines > 2) {
      lineOffset = Math.max(1, Math.min(lineOffset, totalLines - 2))
    }

    const targetLineNum = Math.min(firstLine.number + lineOffset, view.state.doc.lines)
    const targetLine = view.state.doc.line(targetLineNum)

    const relX = Math.max(0, event.clientX - rect.left - 16)
    const approxCol = Math.max(0, Math.round(relX / 8.5))
    const col = Math.min(approxCol, targetLine.text.length)

    return targetLine.from + col
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
        const imageLine = state.doc.lineAt(node.to)
        const next = imageLine.number < state.doc.lines ? state.doc.line(imageLine.number + 1) : null
        const to = next && EXCALIDRAW_COMMENT.test(next.text.trim()) ? next.to : node.to
        const range = blockRange(state, node.from, to)
        const isEditingSource = selection.some(
          (r) => r.empty && r.from > range.from && r.from < range.to,
        )
        if (!isEditingSource) {
          renderBlock(node.from, to, false, true)
          return false
        }
      }
      if (node.name === "Image") {
        if (rendered.some((r) => node.from >= r.from && node.to <= r.to)) return false
        const line = state.doc.lineAt(node.from)
        const lineText = line.text.trim()
        const nodeText = state.doc.sliceString(node.from, node.to).trim()
        if (lineText === nodeText) {
          const next = line.number < state.doc.lines ? state.doc.line(line.number + 1) : null
          const to = next && EXCALIDRAW_COMMENT.test(next.text.trim()) ? next.to : line.to
          const range = blockRange(state, line.from, to)
          const isEditingSource = selection.some(
            (r) => r.empty && r.from > range.from && r.from < range.to,
          )
          if (!isEditingSource) {
            renderBlock(line.from, to, false, true)
            return false
          }
        }
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
      if (node.name === "EmphasisMark") {
        const parent = node.node.parent
        if (parent) {
          const parentText = state.doc.sliceString(parent.from, parent.to)
          if (parentText.includes("LUMINARY_IMG")) return
        }
      }
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
  ".cm-md-block": {
    margin: "6px 0",
    position: "relative",
    whiteSpace: "normal",
    fontSize: "inherit",
  },
  ".cm-md-block .prose": {
    margin: "0 !important",
    maxWidth: "none !important",
    fontSize: "inherit !important",
    lineHeight: "1.65 !important",
  },
  ".cm-md-block .prose > *": {
    marginTop: "0.35rem !important",
    marginBottom: "0.35rem !important",
  },
  ".cm-md-block figure": {
    margin: "0.5rem 0 !important",
  },
  ".cm-line": {
    lineHeight: "1.65",
  },
  ".cm-md-code": {
    fontFamily: "var(--font-mono)",
    fontSize: "0.92em",
    backgroundColor: "hsl(var(--muted) / 0.6)",
  },
  ".cm-md-fence": { color: "hsl(var(--muted-foreground))", opacity: "0.55" },
  ".cm-md-table-line": {
    fontFamily: "var(--font-mono)",
    fontSize: "0.92em",
    letterSpacing: "-0.01em",
    lineHeight: "1.5",
    backgroundColor: "hsl(var(--muted) / 0.25)",
    paddingLeft: "4px",
  },
  ".cm-md-math-line": {
    fontFamily: "var(--font-mono)",
    fontSize: "0.95em",
    backgroundColor: "hsl(var(--primary) / 0.05)",
    borderLeft: "2px solid hsl(var(--primary) / 0.5)",
    paddingLeft: "8px",
  },
  ".cm-md-block img": { maxWidth: "100%", height: "auto" },
  ".cm-md-block table": {
    width: "auto",
    minWidth: "min(100%, 360px)",
    maxWidth: "100%",
    borderCollapse: "collapse",
    margin: "6px 0",
    fontSize: "0.95em",
    lineHeight: "1.45",
  },
  ".cm-md-block th": {
    padding: "6px 12px",
    backgroundColor: "hsl(var(--muted) / 0.6)",
    color: "hsl(var(--foreground))",
    fontWeight: "600",
    fontSize: "0.85em",
    textTransform: "uppercase",
    letterSpacing: "0.04em",
    border: "1px solid hsl(var(--border))",
    textAlign: "left",
    whiteSpace: "nowrap",
  },
  ".cm-md-block td": {
    padding: "6px 12px",
    border: "1px solid hsl(var(--border))",
    color: "hsl(var(--foreground) / 0.9)",
    verticalAlign: "top",
    fontSize: "inherit",
  },
  ".cm-md-block tr:nth-child(even) td": {
    backgroundColor: "hsl(var(--muted) / 0.15)",
  },
  ".cm-md-block tr:hover td": {
    backgroundColor: "hsl(var(--accent) / 0.3)",
  },
  ".cm-md-block pre": {
    fontFamily: "var(--font-mono) !important",
    fontSize: "0.92em !important",
    lineHeight: "1.6 !important",
    padding: "0.85em 1.15em !important",
    margin: "0.5rem 0 !important",
    borderRadius: "0.5rem !important",
  },
  ".cm-md-block pre code": {
    fontFamily: "var(--font-mono) !important",
    fontSize: "inherit !important",
    lineHeight: "inherit !important",
  },
  ".cm-md-block .katex-display": {
    margin: "0.75rem 0 !important",
    padding: "0.4rem 0",
  },
  ".cm-md-block .katex-display > .katex": {
    fontSize: "1.25em !important",
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
function isAtVisualEdge(view: EditorView, head: number, dir: 1 | -1): { atEdge: boolean; visualPos?: number } {
  try {
    if (typeof view.coordsAtPos !== "function" || typeof view.posAtCoords !== "function") {
      return { atEdge: true }
    }
    const coords = view.coordsAtPos(head)
    if (!coords) return { atEdge: true }
    const line = view.state.doc.lineAt(head)
    if (dir === -1) {
      const posAbove = view.posAtCoords({ x: coords.left, y: coords.top - 5 })
      if (posAbove !== null && view.state.doc.lineAt(posAbove).number === line.number && posAbove !== head) {
        return { atEdge: false, visualPos: posAbove }
      }
      return { atEdge: true }
    } else {
      const posBelow = view.posAtCoords({ x: coords.left, y: coords.bottom + 5 })
      if (posBelow !== null && view.state.doc.lineAt(posBelow).number === line.number && posBelow !== head) {
        return { atEdge: false, visualPos: posBelow }
      }
      return { atEdge: true }
    }
  } catch {
    return { atEdge: true }
  }
}

export function stepInto(view: EditorView, field: StateField<DecorationSet>, dir: 1 | -1): boolean {
  const sel = view.state.selection.main
  const { doc } = view.state

  // If there is an active selection (e.g. selected image or text range):
  // collapse to the leading edge in the direction of motion
  let head = sel.head
  if (!sel.empty) {
    head = dir === -1 ? sel.from : sel.to
  }

  const line = doc.lineAt(head)
  const column = head - line.from

  // 1. If moving within wrapped visual lines of the same paragraph, move visually
  const visual = isAtVisualEdge(view, head, dir)
  if (!visual.atEdge && visual.visualPos !== undefined) {
    view.dispatch({ selection: { anchor: visual.visualPos }, scrollIntoView: true })
    return true
  }

  // 2. We are crossing to an adjacent line
  const targetNum = line.number + dir
  if (targetNum < 1) {
    view.dispatch({ selection: { anchor: 0 }, scrollIntoView: true })
    return true
  }
  if (targetNum > doc.lines) {
    view.dispatch({ selection: { anchor: doc.length }, scrollIntoView: true })
    return true
  }

  const targetLine = doc.line(targetNum)
  let anchor: number | null = null

  // Check if target line is inside or covered by a RenderedBlock decoration
  try {
    view.state.field(field).between(targetLine.from, targetLine.to, (from, to, deco) => {
      if (anchor !== null) return
      const widget = deco.spec?.widget
      if (!widget || typeof widget !== "object" || !("source" in widget)) return

      const widgetSource = (widget as { source: string }).source
      const widgetDelimited = Boolean((widget as { delimited?: boolean }).delimited)

      if (isImageOnlyParagraph(widgetSource)) {
        const blockLineFrom = doc.lineAt(from).number
        const blockLineTo = doc.lineAt(to).number
        const nextNum = dir === 1 ? blockLineTo + 1 : blockLineFrom - 1
        if (nextNum >= 1 && nextNum <= doc.lines) {
          anchor = dir === 1 ? doc.line(nextNum).from : doc.line(nextNum).to
        } else {
          anchor = dir === 1 ? doc.line(blockLineTo).to : doc.line(blockLineFrom).from
        }
        return
      }

      const lines = widgetSource.split("\n").length
      const offset =
        dir === 1
          ? firstEditableLine(widgetDelimited)
          : clickedSourceLine(null, lines, widgetDelimited)
      const blockStartLine = doc.lineAt(from).number
      const destLine = doc.line(Math.min(blockStartLine + offset, doc.lines))
      if (destLine.text.includes("|")) {
        const cellPos = caretInTableRow(destLine.text, 0)
        anchor = destLine.from + cellPos
      } else {
        anchor = destLine.from + columnOffset(destLine.text, column)
      }
    })
  } catch {
    // If field lookup fails, fallback to line-based navigation
  }

  if (anchor !== null) {
    view.dispatch({ selection: { anchor }, scrollIntoView: true })
    return true
  }

  // 3. Target line is a normal line or blank line: land on it cleanly without coordinate jumping!
  const col = columnOffset(targetLine.text, column)
  view.dispatch({ selection: { anchor: targetLine.from + col }, scrollIntoView: true })
  return true
}

export function stepHorizontal(view: EditorView, field: StateField<DecorationSet>, dir: 1 | -1): boolean {
  const sel = view.state.selection.main
  if (!sel.empty) return false
  const { doc } = view.state
  const head = sel.head

  try {
    let handled = false
    const decorations = view.state.field(field)

    if (dir === 1) {
      // Forward arrow (ArrowRight)
      decorations.between(head, Math.min(head + 2, doc.length), (from, _to, deco) => {
        if (handled) return
        const widget = deco.spec?.widget
        if (!widget || typeof widget !== "object" || !("source" in widget)) return

        const widgetDelimited = Boolean((widget as { delimited?: boolean }).delimited)
        const blockStartLine = doc.lineAt(from)
        if (head === blockStartLine.from || head === from || head === Math.max(0, from - 1)) {
          const offset = firstEditableLine(widgetDelimited)
          const targetLine = doc.line(Math.min(blockStartLine.number + offset, doc.lines))
          view.dispatch({ selection: { anchor: targetLine.from }, scrollIntoView: true })
          handled = true
        }
      })
    } else {
      // Backward arrow (ArrowLeft)
      decorations.between(Math.max(0, head - 2), head, (from, to, deco) => {
        if (handled) return
        const widget = deco.spec?.widget
        if (!widget || typeof widget !== "object" || !("source" in widget)) return

        const widgetSource = (widget as { source: string }).source
        const widgetDelimited = Boolean((widget as { delimited?: boolean }).delimited)
        const lines = widgetSource.split("\n").length
        const blockStartLine = doc.lineAt(from)

        if (head === to || head === Math.min(doc.length, to + 1)) {
          const offset = clickedSourceLine(null, lines, widgetDelimited)
          const targetLine = doc.line(Math.min(blockStartLine.number + offset, doc.lines))
          view.dispatch({ selection: { anchor: targetLine.to }, scrollIntoView: true })
          handled = true
        }
      })
    }

    if (handled) return true
  } catch {
    // fallback
  }

  return false
}

export function liveField(options: LiveMarkdownOptions) {
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
    Prec.high(
      keymap.of([
        { key: "ArrowDown", run: (view) => stepInto(view, field, 1) },
        { key: "ArrowUp", run: (view) => stepInto(view, field, -1) },
        { key: "ArrowRight", run: (view) => stepHorizontal(view, field, 1) },
        { key: "ArrowLeft", run: (view) => stepHorizontal(view, field, -1) },
      ]),
    ),
    // Inline, so it beats the base theme's monospace rule whatever order the
    // two style modules are mounted in. Prose is what is being written here.
    EditorView.contentAttributes.of({ style: "font-family: var(--font-sans)" }),
    liveTheme,
  ]
}
