/**
 * Pure cloze-parsing helpers, kept out of ClozeCard.tsx so the component file
 * exports only components (fast refresh) and the parser stays unit-testable.
 */

export type ClozeSegment =
  | { type: "text"; content: string }
  | { type: "blank"; term: string }

/** Parse cloze_text into alternating text and blank segments. */
export function parseClozeSegments(clozeText: string): ClozeSegment[] {
  const parts = clozeText.split(/(\{\{.+?\}\})/g)
  return parts.map((part) => {
    const match = /^\{\{(.+?)\}\}$/.exec(part)
    return match
      ? { type: "blank" as const, term: match[1] }
      : { type: "text" as const, content: part }
  })
}
