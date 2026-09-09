/**
 * What a live-rendered markdown editor may hide, and when.
 *
 * Not "hide the syntax": a marker on the line being edited has to stay, or the
 * writer is editing something they cannot see. Everywhere else the source is
 * the rendering.
 */

export interface TextRange {
  from: number
  to: number
}

/** Lezer node names, from `@codemirror/lang-markdown`'s grammar. */
export function hidesMark(name: string, parentName?: string | null): boolean {
  switch (name) {
    case "HeaderMark":
    case "QuoteMark":
    case "EmphasisMark":
    case "StrikethroughMark":
      return true
    // A fence owns its whole line, and hiding it leaves a blank one standing
    // where a code block starts. Inline backticks sit inside the text.
    case "CodeMark":
      return parentName === "InlineCode"
    // Only a link's own: an image keeps its `!` and alt visible when it sits
    // in a line of prose, because nothing renders it there.
    case "LinkMark":
    case "URL":
      return parentName === "Link"
    default:
      return false
  }
}

/**
 * Inclusive at both ends: a cursor resting at the end of a line is on it, and
 * so is one at its start.
 */
export function lineIsBeingEdited(
  ranges: readonly TextRange[],
  lineFrom: number,
  lineTo: number,
): boolean {
  return ranges.some((r) => r.from <= lineTo && r.to >= lineFrom)
}

/** Blocks the editor draws with the app's own renderer rather than as source. */
export function rendersAsBlock(name: string): boolean {
  return name === "FencedCode" || name === "Table" || name === "HorizontalRule"
}

/**
 * Blocks whose first and last source lines are delimiters -- ``` and $$. A
 * caret placed on one of those and a single keystroke stops the block being a
 * block, which is what made editing one throw the text below it around.
 */
export function isDelimitedBlock(name: string): boolean {
  return name === "FencedCode" || name === "MathBlock"
}

/**
 * Which line of a block's source a click inside its rendering belongs to.
 *
 * A table's rows map to source lines one for one past the delimiter row.
 * Anything else answers with its last line -- except a delimited block, where
 * the last line is a fence and the answer is the last line of content.
 */
export function clickedSourceLine(
  rowIndex: number | null,
  sourceLines: number,
  delimited = false,
): number {
  const last = delimited ? sourceLines - 2 : sourceLines - 1
  const bounded = (n: number) => Math.min(Math.max(n, delimited ? 1 : 0), Math.max(last, 0))
  if (rowIndex === null) return bounded(last)
  if (rowIndex === 0) return bounded(0)
  return bounded(rowIndex + 1)
}

/**
 * Blocks with nothing to show: an HTML comment carries the excalidraw sidecar
 * beside a diagram, and renders to nothing at all. The grammar spells a comment
 * three ways depending on whether it interrupts a paragraph.
 */
export function hidesBlock(name: string): boolean {
  return name === "HTMLBlock" || name === "CommentBlock" || name === "Comment"
}

/** A paragraph that is nothing but an image is a block, whatever the parser calls it. */
export function isImageOnlyParagraph(source: string): boolean {
  return /^!\[[^\]]*\]\([^)\s]+\)$/.test(source.trim())
}

/**
 * `$$ … $$` regions, which no markdown parser here knows about: the CodeMirror
 * grammar has no math extension, so the display block is found in the text.
 * Ranges are [start of the opening line, end of the closing line]; an unclosed
 * block is not one.
 */
export function mathBlockRanges(text: string): TextRange[] {
  const found: TextRange[] = []
  const lines = text.split("\n")
  let offset = 0
  let openFrom: number | null = null
  for (const line of lines) {
    if (line.trim() === "$$") {
      if (openFrom === null) openFrom = offset
      else {
        found.push({ from: openFrom, to: offset + line.length })
        openFrom = null
      }
    }
    offset += line.length + 1
  }
  return found
}

/**
 * Where the caret goes inside a table row when a cell is clicked: the end of
 * that cell's text, or just inside an empty one. The row's own end is not an
 * answer -- typing there appends past the last pipe instead of into the column
 * the writer aimed at.
 */
export function caretInTableRow(row: string, cellIndex: number): number {
  const parts = row.split("|")
  const target = cellIndex + 1
  if (target >= parts.length) return row.length
  const before = parts.slice(0, target).join("|").length + 1
  const cell = parts[target]
  if (cell.trim() === "") return before + (cell.length > 0 ? 1 : 0)
  return before + cell.trimEnd().length
}

/** The first line of a block a caret may rest on, arriving from above. */
export function firstEditableLine(delimited: boolean): number {
  return delimited ? 1 : 0
}
