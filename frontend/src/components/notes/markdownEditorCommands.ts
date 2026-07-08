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
