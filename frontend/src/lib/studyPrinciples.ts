// A line about how learning actually works, shown while setup runs.
//
// Dead time is the cheapest place to teach someone the idea the product is
// built on. These are established findings from learning research stated
// plainly -- no attributions, because a misattributed quote is worse than none.
//
// The list lives in src-tauri/boot/principles.json because the Tauri boot
// screen shows one too, before the SPA exists, and it can only read a file
// sitting beside it. One source, two consumers.

import principles from "../../../src-tauri/boot/principles.json"

export const STUDY_PRINCIPLES: readonly string[] = principles

/**
 * The same line for a whole day, a different one tomorrow.
 *
 * Deterministic rather than random so it does not flicker between renders or
 * change on every relaunch. Must match the boot screen's copy of this.
 */
export function principleOfTheDay(now: Date = new Date()): string {
  const startOfYear = Date.UTC(now.getUTCFullYear(), 0, 0)
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())
  const dayOfYear = Math.floor((today - startOfYear) / 86_400_000)
  return STUDY_PRINCIPLES[dayOfYear % STUDY_PRINCIPLES.length]
}
