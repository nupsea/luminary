// Where a citation points, in the terms its source actually has.
//
// "p.151" is the right answer for a book and the wrong one for a lecture, a
// source file or a web page, and a citation that names a page for all four is
// telling the reader something untrue about three of them. Each source type
// carries exactly one locus that a reader can act on:
//
//   a paginated document   p.151          the page they can turn to
//   a recording            14:22          the moment they can seek to
//   anything else          the section    the heading they can scroll to
//
// A source file's line ("L214") is not here because nothing can supply it yet:
// the code chunker stores its start line in `chunks.page_number` and marks the
// chunk in no other way, so a citation cannot tell a line from a page.
//
// A source with none of those has no locus, and `formatLocus` returns null
// rather than inventing one -- a fabricated locus is worse than an absent one,
// because it looks checkable and is not.

export type CitationLocus =
  | { kind: "time"; seconds: number }
  | { kind: "page"; page: number; label?: string | null }
  | { kind: "section"; heading: string }

/** What a citation knows about where it came from. */
export interface LocusSource {
  /** Seconds into a recording. */
  startTime?: number | null
  /** The sheet the viewer scrolls to. */
  page?: number | null
  /** What that sheet is printed as, when the book numbers front matter apart. */
  pageLabel?: string | null
  heading?: string | null
}

/**
 * The one locus this source can support, most specific first.
 *
 * A recording's moment outranks everything: an audio document has a section per
 * transcript window whose heading is empty by design (I-30), so falling through
 * to the heading would produce a chip that names nothing. A page outranks a
 * heading for the same reason in the other direction -- a 40-page chapter is not
 * a location.
 */
export function locusOf(source: LocusSource): CitationLocus | null {
  if (source.startTime != null && source.startTime >= 0) {
    return { kind: "time", seconds: source.startTime }
  }
  if (source.page != null && source.page > 0) {
    return { kind: "page", page: source.page, label: source.pageLabel }
  }
  const heading = (source.heading ?? "").trim()
  if (heading) return { kind: "section", heading }
  return null
}

/** Seconds as a reader would read a timestamp: 862.5 -> "14:22", 3725 -> "1:02:05". */
export function formatTimestamp(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds))
  const hh = Math.floor(whole / 3600)
  const mm = Math.floor((whole % 3600) / 60)
  const ss = whole % 60
  const pad = (n: number) => String(n).padStart(2, "0")
  return hh > 0 ? `${hh}:${pad(mm)}:${pad(ss)}` : `${mm}:${pad(ss)}`
}

/**
 * The locus as a chip shows it, or null when the source has none.
 *
 * Null is a real answer and callers must render nothing for it. The page form
 * prefers the printed label over the sheet number, because the sheet is what the
 * viewer scrolls to and the label is what the reader sees on the paper -- on a
 * 613-page book measured here, sheet 41 is printed "19".
 */
export function formatLocus(locus: CitationLocus | null): string | null {
  if (!locus) return null
  switch (locus.kind) {
    case "time":
      return formatTimestamp(locus.seconds)
    case "page": {
      const label = (locus.label ?? "").trim()
      return `p.${label || locus.page}`
    }
    case "section":
      return locus.heading
  }
}
