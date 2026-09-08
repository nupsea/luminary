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

/**
 * Blocks the editor draws with the app's own renderer rather than as source.
 * An HTML comment is not one of them: it carries the excalidraw sidecar and
 * renders to nothing, so it is hidden outright.
 */
export function rendersAsBlock(name: string): boolean {
  return name === "FencedCode" || name === "Table"
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
