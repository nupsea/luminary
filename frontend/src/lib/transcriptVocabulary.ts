// Personal transcript vocabulary and the fixes a learner makes to a transcript.
import type { components } from "@/types/api"

type TranscriptCorrection = components["schemas"]["TranscriptCorrection"]
export type TranscriptFixResult = components["schemas"]["TranscriptFixResponse"]

/** One term per line or comma; blank entries dropped, first spelling of a duplicate kept. */
export function parseTerms(text: string): string[] {
  const seen = new Set<string>()
  const terms: string[] = []
  for (const raw of text.split(/[\n,]/)) {
    const term = raw.trim().replace(/\s+/g, " ")
    const key = term.toLowerCase()
    if (term && !seen.has(key)) {
      seen.add(key)
      terms.push(term)
    }
  }
  return terms
}

/** "Speech recognition, 5 terms corrected" -- where the transcript came from, and what changed. */
export function transcriptSourceLabel(
  source: string | null | undefined,
  corrections: TranscriptCorrection[],
): string | null {
  const base =
    source === "captions" ? "Uploader's captions" : source === "speech" ? "Speech recognition" : null
  if (!base) return null
  const applied = corrections.filter((c) => (c.count ?? 0) > 0)
  if (applied.length === 0) return base
  return `${base}, ${applied.length} term${applied.length === 1 ? "" : "s"} corrected`
}

export function fixResultMessage(heard: string, term: string, r: TranscriptFixResult): string {
  if (r.occurrences === 0) return `"${heard}" does not appear in this transcript.`
  const times = r.occurrences === 1 ? "once" : `${r.occurrences} times`
  const kept = r.vocabulary_added ? ` "${term}" is now in your vocabulary.` : ""
  return `Replaced "${heard}" with "${term}" ${times}.${kept}`
}
