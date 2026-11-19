import { describe, expect, it } from "vitest"

import { COLOR_IDS, ago, libraryColor, libraryIdFor, libraryInitials, libraryTitle } from "./libraryLook"

describe("libraryTitle", () => {
  it("uses the name, else the id as words", () => {
    expect(libraryTitle({ id: "work", name: "Acme" })).toBe("Acme")
    expect(libraryTitle({ id: "kids_books", name: null })).toBe("Kids books")
    expect(libraryTitle({ id: "default" })).toBe("Default")
  })
})

describe("libraryInitials", () => {
  it("takes two words' first letters, or one word's first two", () => {
    expect(libraryInitials("Kids Books")).toBe("KB")
    expect(libraryInitials("personal")).toBe("Pe")
    expect(libraryInitials("  ")).toBe("?")
  })
})

describe("libraryColor", () => {
  it("keeps a chosen colour and gives an unset one a stable colour", () => {
    expect(libraryColor({ id: "work", color: "rose" })).toBe("rose")
    const first = libraryColor({ id: "work", color: null })
    expect(COLOR_IDS).toContain(first)
    expect(libraryColor({ id: "work", color: null })).toBe(first)
  })
})

describe("libraryIdFor", () => {
  it("makes a path-safe id the backend accepts", () => {
    const id = libraryIdFor("Kids' Café Books!", [])
    expect(id).toBe("kids-cafe-books")
    expect(id).toMatch(/^[a-z0-9][a-z0-9_-]{0,62}$/)
  })

  it("never reuses a taken id, the default's included", () => {
    expect(libraryIdFor("Default", ["default"])).toBe("default-2")
    expect(libraryIdFor("Work", ["work", "work-2"])).toBe("work-3")
  })

  it("names an unnameable library something", () => {
    expect(libraryIdFor("!!!", [])).toBe("library")
  })
})

describe("ago", () => {
  const now = Date.parse("2026-11-18T12:00:00Z")
  it("reads as a person would say it", () => {
    expect(ago("2026-11-18T11:59:50Z", now)).toBe("just now")
    expect(ago("2026-11-18T11:15:00Z", now)).toBe("45 min ago")
    expect(ago("2026-11-18T10:00:00Z", now)).toBe("2 hours ago")
    expect(ago("2026-11-16T12:00:00Z", now)).toBe("2 days ago")
  })
})
