/**
 * Pure utility functions for Note node graph behavior
 *
 * These functions have no React/Zustand imports so they can be tested
 * in vitest "node" environment (per patterns.md).
 */

/** Indigo color for Note nodes in the Viz graph */
export const NOTE_NODE_COLOR = "#6366f1"

/**
 * Compute the display size for a Note node based on outgoing link count.
 * Mirrors the formula in Viz.tsx buildGraph.
 */
export function computeNoteNodeSize(outgoingLinkCount: number): number {
  return Math.max(8, Math.sqrt(outgoingLinkCount) * 5)
}

/**
 * Return the node attributes (color, type, size) for a Note node.
 * Used in buildGraph to assign the correct renderer and style.
 */
export function noteNodeAttrs(
  label: string,
  noteId: string,
  outgoingLinkCount: number,
): {
  label: string
  entityType: string
  note_id: string
  color: string
  type: string
  size: number
} {
  return {
    label,
    entityType: "note",
    note_id: noteId,
    color: NOTE_NODE_COLOR,
    type: "square",
    size: computeNoteNodeSize(outgoingLinkCount),
  }
}

/**
 * Build the detail payload for a luminary:navigate event targeting a note.
 * Pure function -- testable in node environment.
 */
export function buildNoteNavigateDetail(noteId: string): { tab: string; filter: string } {
  return { tab: "notes", filter: noteId }
}

/**
 * Dispatch the luminary:navigate event to open the Notes tab filtered to a note.
 * Per I-11: cross-tab navigation uses the luminary:navigate DOM event.
 * Calls window.dispatchEvent -- only call from browser context.
 */
export function navigateToNote(noteId: string): void {
  window.dispatchEvent(
    new CustomEvent("luminary:navigate", { detail: buildNoteNavigateDetail(noteId) }),
  )
}
