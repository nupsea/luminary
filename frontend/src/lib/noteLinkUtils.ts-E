/**
 * Pure utilities for note-to-note [[id|text]] link markers.
 * Extracted into a standalone file so Vitest can test them without
 * triggering React or Zustand store imports.
 */

export const LINK_MARKER_RE = /\[\[([a-f0-9-]+)\|([^\]]+)\]\]/g

/** Parsed link marker extracted from note content. */
export interface LinkMarker {
  raw: string        // The full [[id|text]] token
  id: string         // Note ID
  text: string       // Display text
  offset: number     // Character offset in the source string
}

/**
 * Parse all [[id|text]] markers from a content string.
 * Returns markers in order of appearance.
 */
export function parseLinkMarkers(content: string): LinkMarker[] {
  const results: LinkMarker[] = []
  const re = new RegExp(LINK_MARKER_RE.source, "g")
  let m: RegExpExecArray | null
  while ((m = re.exec(content)) !== null) {
    results.push({
      raw: m[0],
      id: m[1],
      text: m[2],
      offset: m.index,
    })
  }
  return results
}

/**
 * Build a [[id|text]] marker string.
 * Used when inserting a link into the note editor.
 */
export function buildLinkMarker(id: string, text: string): string {
  // Truncate preview to 60 chars to keep markers compact
  const safeText = text.slice(0, 60).replace(/[\[\]|]/g, "")
  return `[[${id}|${safeText}]]`
}

/**
 * Replace [[id|text]] markers in content with plain text previews.
 * Used for note list previews where chip rendering is not desired.
 */
export function stripLinkMarkers(content: string): string {
  return content.replace(LINK_MARKER_RE, (_match, _id, text) => `[${text}]`)
}

/**
 * Detect if the cursor position in a textarea is inside a `[[` trigger.
 * Returns the partial query string after `[[` if detected, or null otherwise.
 *
 * Example: "Hello [[wor" at cursor 11 → returns "wor"
 */
export function detectLinkTrigger(
  value: string,
  cursorPos: number,
): string | null {
  const before = value.slice(0, cursorPos)
  const idx = before.lastIndexOf("[[")
  if (idx === -1) return null
  // Make sure there is no closing ]] between [[ and cursor
  const between = before.slice(idx + 2)
  if (between.includes("]]") || between.includes("[[")) return null
  return between
}

/**
 * Insert a [[id|text]] marker into a textarea value at the `[[` trigger position.
 * Returns the new string value and the new cursor position after the marker.
 */
export function insertLinkAtTrigger(
  value: string,
  cursorPos: number,
  id: string,
  text: string,
): { newValue: string; newCursorPos: number } {
  const before = value.slice(0, cursorPos)
  const after = value.slice(cursorPos)
  const idx = before.lastIndexOf("[[")
  if (idx === -1) {
    return { newValue: value, newCursorPos: cursorPos }
  }
  const marker = buildLinkMarker(id, text)
  const newValue = value.slice(0, idx) + marker + after
  const newCursorPos = idx + marker.length
  return { newValue, newCursorPos }
}
