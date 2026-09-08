/**
 * Merging a captured passage into a note that is already being written.
 * A docked composer stays open while the reader keeps selecting, so the
 * second capture has somewhere to go; a modal one could only ever have a
 * first.
 */
export function appendCapture(draft: string, capture: string): string {
  if (!capture.trim()) return draft
  if (!draft.trim()) return capture
  return `${draft.replace(/\s+$/, "")}\n\n${capture}`
}
