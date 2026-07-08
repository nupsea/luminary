import type { EditorState, TransactionSpec } from "@codemirror/state"

// Mirrors the old insertAtTextareaCursor semantics: the block lands in its own
// paragraph with blank lines around it (mermaid/excalidraw insertions).
export function insertBlockSpec(state: EditorState, markdown: string): TransactionSpec {
  const { from, to } = state.selection.main
  const before = state.sliceDoc(0, from)
  const after = state.sliceDoc(to)
  const prefix = from > 0 && !before.endsWith("\n") ? "\n\n" : ""
  const suffix = after.startsWith("\n") ? "" : "\n\n"
  const insertion = `${prefix}${markdown}${suffix}`
  return {
    changes: { from, to, insert: insertion },
    selection: { anchor: from + insertion.length },
    scrollIntoView: true,
  }
}

export function insertInlineSpec(state: EditorState, text: string): TransactionSpec {
  const { from, to } = state.selection.main
  return {
    changes: { from, to, insert: text },
    selection: { anchor: from + text.length },
    scrollIntoView: true,
  }
}

export function replaceSelectionSpec(
  state: EditorState,
  fn: (selected: string) => string,
): TransactionSpec {
  const { from, to } = state.selection.main
  const next = fn(state.sliceDoc(from, to))
  return {
    changes: { from, to, insert: next },
    selection: { anchor: from + next.length },
    scrollIntoView: true,
  }
}

// Rewrite the |size pipe of the image whose URL matches the rendered src.
// Mirrored images render as <apiBase>/images/local/... but are authored as
// __LUMINARY_IMG__/..., so both spellings are tried.
export function setImageSizeInMarkdown(
  content: string,
  src: string,
  size: string,
  apiBase?: string,
): string {
  const candidates = [src]
  if (apiBase && src.startsWith(`${apiBase}/images/local/`)) {
    candidates.push(src.replace(`${apiBase}/images/local/`, "__LUMINARY_IMG__/"))
  }
  for (const url of candidates) {
    const closeIdx = content.indexOf(`](${url})`)
    if (closeIdx === -1) continue
    const openIdx = content.lastIndexOf("![", closeIdx)
    if (openIdx === -1) continue
    const alt = content.slice(openIdx + 2, closeIdx)
    const base = alt.split("|")[0].trim() || "Image"
    const end = closeIdx + 2 + url.length + 1
    return `${content.slice(0, openIdx)}![${base}|${size}](${url})${content.slice(end)}`
  }
  return content
}

// Toggle **strong** / *emphasis* markers around the selection. An empty
// selection gets an open pair with the cursor inside.
export function toggleInlineMarkSpec(state: EditorState, marker: string): TransactionSpec {
  const { from, to } = state.selection.main
  const selected = state.sliceDoc(from, to)
  const mlen = marker.length

  if (selected.startsWith(marker) && selected.endsWith(marker) && selected.length >= mlen * 2) {
    const inner = selected.slice(mlen, selected.length - mlen)
    return {
      changes: { from, to, insert: inner },
      selection: { anchor: from, head: from + inner.length },
    }
  }

  const beforeMark = state.sliceDoc(Math.max(0, from - mlen), from)
  const afterMark = state.sliceDoc(to, Math.min(state.doc.length, to + mlen))
  if (beforeMark === marker && afterMark === marker) {
    return {
      changes: { from: from - mlen, to: to + mlen, insert: selected },
      selection: { anchor: from - mlen, head: from - mlen + selected.length },
    }
  }

  return {
    changes: { from, to, insert: `${marker}${selected}${marker}` },
    selection: selected
      ? { anchor: from + mlen, head: from + mlen + selected.length }
      : { anchor: from + mlen },
  }
}
