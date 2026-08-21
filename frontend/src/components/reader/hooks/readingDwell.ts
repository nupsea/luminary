// What counts as reading a section, as a pure rule so it can be tested.
//
// Opening a document and clicking around is not reading it, and the reader has
// two surfaces that both carry `data-section-id` -- the prose and the contents
// list -- so "visible" alone was never the right test.

// How long a section must hold the screen before it counts as read. Bracketed
// by two cases: a fast scroll on the way somewhere else holds a section for
// roughly a second, which must not count; and a short paragraph of ~50 words is
// about 15s at the 200 wpm convention in `readingTime.ts`, which would be too
// strict to require, since skimming is still reading.
//
// This is a proxy for attention, not a measurement of it. It cannot tell
// reading from a page left open, so nothing downstream may describe it as time
// spent reading -- `time_on_task` is the measured one.
export const DWELL_MS = 5000

// Half the section on screen.
export const SECTION_VISIBLE_RATIO = 0.5
// ...or the section filling half the screen. A section taller than twice the
// viewport can never reach the ratio above, so a ratio test alone silently
// never fires on long sections -- one measured document holds 5,063,040
// characters in a single section.
export const VIEWPORT_COVERED_RATIO = 0.5

// Ratios the observer reports at. Without intermediate steps a tall section
// jumps from 0 to a value below the threshold and never fires a callback while
// it is the only thing on screen.
export const THRESHOLDS = [0, 0.25, 0.5, 0.75, 1]

/** The subset of IntersectionObserverEntry the rule reads. */
export interface VisibilitySample {
  isIntersecting: boolean
  intersectionRatio: number
  intersectionHeight: number
  rootHeight: number
}

export function isBeingRead(sample: VisibilitySample): boolean {
  if (!sample.isIntersecting) return false
  if (sample.intersectionRatio >= SECTION_VISIBLE_RATIO) return true
  if (sample.rootHeight <= 0) return false
  return sample.intersectionHeight / sample.rootHeight >= VIEWPORT_COVERED_RATIO
}

export function sampleFromEntry(entry: IntersectionObserverEntry): VisibilitySample {
  return {
    isIntersecting: entry.isIntersecting,
    intersectionRatio: entry.intersectionRatio,
    intersectionHeight: entry.intersectionRect.height,
    rootHeight: entry.rootBounds?.height ?? 0,
  }
}
