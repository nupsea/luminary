// Words per minute. Bracketing cases: technical prose carrying code and
// formulae is read closer to 150, light narrative closer to 250, and this
// library holds both. 200 sits between them and is the figure the estimate is
// labelled with, never presented as measured.
const WORDS_PER_MINUTE = 200

/**
 * Roughly how long is left in a document, or null when it cannot be estimated.
 *
 * Two approximations stack here and the label has to carry both. Reading speed
 * is a convention, not a measurement of this reader. And progress is sections
 * read over sections total, so the words remaining assume sections of roughly
 * equal length -- on a book whose first chapter is a page and whose fourth is
 * forty, that is wrong in whichever direction the reader happens to be.
 *
 * Returned as an approximation for a caller that prints "~N min left". A
 * document with no recorded word count yields null rather than a zero, because
 * "no estimate" and "nothing left to read" are opposite statements.
 */
export function readingMinutesLeft(
  wordCount: number | null | undefined,
  progressPct: number,
): number | null {
  if (!wordCount || wordCount <= 0) return null
  const remaining = wordCount * (1 - Math.min(Math.max(progressPct, 0), 1))
  if (remaining <= 0) return null
  return Math.max(1, Math.round(remaining / WORDS_PER_MINUTE))
}

/** "~8 min left", or null when there is nothing to base it on. */
export function readingTimeLabel(
  wordCount: number | null | undefined,
  progressPct: number,
): string | null {
  const minutes = readingMinutesLeft(wordCount, progressPct)
  return minutes === null ? null : `~${minutes} min left`
}
