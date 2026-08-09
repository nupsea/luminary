import { looksLikeHeading } from "./pdfTocUtils"

const MAX_DERIVED = 64

/**
 * A readable title for a section.
 *
 * Some PDFs (Google Docs exports) carry anchor names where a bookmark title
 * should be, so the stored heading is `_r9szt46p8rxa`. Dropping those entries
 * empties the contents panel, which is worse than a bad label -- the reader
 * loses navigation. Fall back to the section's own opening text instead.
 */
export function sectionTitle(section: {
  heading?: string | null
  preview?: string | null
  content?: string | null
}): string {
  const heading = (section.heading ?? "").trim()
  if (heading && looksLikeHeading(heading)) return heading

  const derived = derivedFromPreview(section.preview ?? section.content ?? "")
  if (derived) return derived
  return heading || "(Untitled section)"
}

/**
 * Whether the source authored a heading. `sectionTitle` always returns
 * something for the contents panel, but only an authored heading may be drawn
 * in the reading flow.
 */
export function hasAuthoredHeading(section: { heading?: string | null }): boolean {
  const heading = (section.heading ?? "").trim()
  return heading.length > 0 && looksLikeHeading(heading)
}

function derivedFromPreview(preview: string): string {
  const clean = preview.replace(/\s+/g, " ").trim()
  if (!clean) return ""
  // Prefer a sentence boundary so the label is not cut mid-clause.
  const sentence = clean.split(/(?<=[.?!:])\s/)[0] ?? clean
  const candidate = sentence.length <= MAX_DERIVED ? sentence : clean.slice(0, MAX_DERIVED)
  const trimmed = candidate.trim().replace(/[\s.,;:]+$/, "")
  if (!trimmed) return ""
  return trimmed.length < clean.length ? `${trimmed}…` : trimmed
}

/**
 * Relabel sections, then drop the ones still unreadable.
 *
 * Neither half works alone: dropping everything empties the panel when a whole
 * document has anchor-id headings, and relabelling alone leaves a textbook's
 * stray glyphs ("c", "g", "our move{") in the contents. Falls back to the
 * relabelled list when filtering would leave nothing to navigate with.
 */
export function usableSections<T extends { heading?: string | null; preview?: string | null; content?: string | null }>(
  sections: T[],
): (T & { heading: string })[] {
  const relabelled = sections.map(s => ({ ...s, heading: sectionTitle(s) }))
  const kept = relabelled.filter(s => looksLikeHeading(s.heading))
  return kept.length > 0 ? kept : relabelled
}
