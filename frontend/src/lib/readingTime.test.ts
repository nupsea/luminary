import { describe, expect, it } from "vitest"

import { readingMinutesLeft, readingTimeLabel } from "./readingTime"

describe("readingMinutesLeft", () => {
  it("estimates from the words not yet read", () => {
    // 8031 words at 21.9% read -> ~6270 words left -> 31 min at 200 wpm.
    expect(readingMinutesLeft(8031, 0.219)).toBe(31)
    expect(readingMinutesLeft(2619, 0.615)).toBe(5)
  })

  it("has no estimate without a word count", () => {
    // Not zero: "no estimate" and "nothing left to read" are opposite claims,
    // and a 0 here would render as "finished" on a document barely started.
    expect(readingMinutesLeft(null, 0.2)).toBeNull()
    expect(readingMinutesLeft(undefined, 0.2)).toBeNull()
    expect(readingMinutesLeft(0, 0.2)).toBeNull()
  })

  it("never reports less than a minute of reading as nothing", () => {
    expect(readingMinutesLeft(50, 0)).toBe(1)
  })

  it("has nothing left to say about a finished document", () => {
    expect(readingMinutesLeft(5000, 1)).toBeNull()
  })

  it("clamps progress that arrives outside 0..1", () => {
    expect(readingMinutesLeft(4000, -0.5)).toBe(20)
    expect(readingMinutesLeft(4000, 1.5)).toBeNull()
  })
})

describe("readingTimeLabel", () => {
  it("marks the number as approximate", () => {
    // The label carries the tilde because two approximations stack underneath:
    // a conventional reading speed, and progress counted in sections.
    expect(readingTimeLabel(8031, 0.219)).toBe("~31 min left")
  })

  it("says nothing rather than guessing", () => {
    expect(readingTimeLabel(null, 0.2)).toBeNull()
  })
})
