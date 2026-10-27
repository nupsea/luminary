import type { ReaderTab } from "./readerLandingTab"

/** Where the reader was: the view, and in the Read view the section their own scrolling reached. */
export interface ReadingSpot {
  tab: ReaderTab
  sectionId: string | null
}

/**
 * The spot a chapter run returns to when it ends (#231). Revealing an answer moves the
 * view to the card's source, so only the spot before the run's first reveal is held.
 */
export function createPracticeReturn() {
  let held: ReadingSpot | null = null
  return {
    hold(spot: ReadingSpot) {
      held ??= spot
    },
    release(): ReadingSpot | null {
      const spot = held
      held = null
      return spot
    },
  }
}
