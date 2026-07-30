import type { Root } from "hast"

export const SOURCE_LINE_ATTR = "data-src-line"

/**
 * Stamp each top-level rendered block with the markdown line it came from, so
 * scroll sync can map a source position to a pixel offset in the preview.
 *
 * Only root-level children are stamped. They correspond one-for-one with the
 * source blocks a scroll position lands in, and keeping the set small keeps the
 * per-sync DOM query cheap. Nodes whose position was lost (raw HTML re-parsed by
 * rehype-raw) are skipped — the sync interpolates across the gap.
 */
export function rehypeSourceLine(lineOffset = 0) {
  return (tree: Root) => {
    for (const node of tree.children) {
      if (node.type !== "element") continue
      const line = node.position?.start.line
      if (line == null) continue
      node.properties = {
        ...node.properties,
        [SOURCE_LINE_ATTR]: String(line + lineOffset),
      }
    }
  }
}

/**
 * Lines preceding `index` in `source`.
 *
 * A note containing diagrams is rendered as several markdown chunks split around
 * them, and each chunk's positions restart at line 1. Without this offset the
 * stamped lines would repeat and the mapping would fold back on itself.
 */
export function lineOffsetAt(source: string, index: number): number {
  let lines = 0
  for (let i = 0; i < index && i < source.length; i++) {
    if (source[i] === "\n") lines++
  }
  return lines
}
