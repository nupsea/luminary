import { describe, expect, it } from "vitest"

import { QUOTES, quoteOfTheDay } from "./quotes"

const at = (year: number, month: number, day: number, offset = 0) =>
  quoteOfTheDay(new Date(Date.UTC(year, month, day, 12)), offset)

describe("the collection", () => {
  it("has enough entries that a week never repeats", () => {
    expect(QUOTES.length).toBeGreaterThanOrEqual(14)
  })

  it("attributes and sources every quote", () => {
    for (const q of QUOTES) {
      expect(q.text.length, `empty text: ${JSON.stringify(q)}`).toBeGreaterThan(10)
      expect(q.author.trim(), `missing author: ${q.text}`).not.toBe("")
      expect(q.source.trim(), `missing source: ${q.text}`).not.toBe("")
    }
  })

  it("never prints an unresolved attribution", () => {
    // A hedge like "attributed to X" on the card means the entry should have
    // been dropped, not shipped with a disclaimer.
    for (const q of QUOTES) {
      expect(q.author.toLowerCase()).not.toContain("attributed")
      expect(q.author.toLowerCase()).not.toContain("unknown")
      expect(q.author.toLowerCase()).not.toContain("anonymous")
    }
  })

  it("does not repeat a quote", () => {
    const seen = new Set(QUOTES.map((q) => q.text))
    expect(seen.size).toBe(QUOTES.length)
  })

  it("keeps the famous misattribution correct", () => {
    // Aristotle never wrote it; Will Durant did, summarising him.
    const durant = QUOTES.find((q) => q.text.startsWith("We are what we repeatedly do"))
    expect(durant?.author).toBe("Will Durant")
  })
})

describe("quoteOfTheDay", () => {
  it("is stable for a whole day and changes the next", () => {
    const morning = quoteOfTheDay(new Date(Date.UTC(2026, 7, 3, 6)))
    const evening = quoteOfTheDay(new Date(Date.UTC(2026, 7, 3, 23, 59)))
    const tomorrow = quoteOfTheDay(new Date(Date.UTC(2026, 7, 4, 6)))

    expect(morning).toEqual(evening)
    expect(tomorrow).not.toEqual(morning)
  })

  it("returns a real quote on every day of the year", () => {
    for (let day = 0; day < 366; day++) {
      const q = quoteOfTheDay(new Date(Date.UTC(2026, 0, 1 + day, 12)))
      expect(QUOTES).toContain(q)
    }
  })

  it("shows a different quote per surface on the same day", () => {
    // The hub and the setup screen are both visible at once on a fresh install.
    expect(at(2026, 7, 3, 7)).not.toEqual(at(2026, 7, 3, 0))
  })

  it("walks the whole collection rather than favouring a few", () => {
    const seen = new Set<string>()
    for (let day = 0; day < QUOTES.length; day++) {
      seen.add(quoteOfTheDay(new Date(Date.UTC(2026, 0, 1 + day, 12))).text)
    }
    expect(seen.size).toBe(QUOTES.length)
  })

  it("handles a year boundary without falling off the list", () => {
    expect(QUOTES).toContain(at(2026, 11, 31))
    expect(QUOTES).toContain(at(2027, 0, 1))
  })
})
