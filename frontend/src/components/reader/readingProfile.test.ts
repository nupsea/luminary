import { describe, expect, it } from "vitest"
import { profileSpec, readingProfile, resolveReadingLayout } from "@/components/reader/readingProfile"

describe("readingProfile", () => {
  it("reads a novel as prose", () => {
    expect(readingProfile({ content_type: "book", structure_type: "book" })).toBe("prose")
    expect(readingProfile({ content_type: "epub" })).toBe("prose")
  })

  it("separates technical books from articles and papers", () => {
    expect(readingProfile({ content_type: "tech_book" })).toBe("technical")
    expect(readingProfile({ content_type: "tech_article" })).toBe("article")
    expect(readingProfile({ content_type: "paper" })).toBe("paper")
  })

  it("lets structure_type name a layout content_type cannot express", () => {
    // A recorded technical talk: content_type says audio, only structure_type
    // knows it is dialogue.
    expect(readingProfile({ content_type: "audio", structure_type: "chat" })).toBe("dialogue")
    expect(readingProfile({ content_type: "book", structure_type: "script" })).toBe("script")
  })

  it("does not let a duplicate structure_type override content_type", () => {
    // "book" and "paper" exist on both axes; content_type is the finer of the
    // two, so a technical book must keep its wider measure.
    expect(readingProfile({ content_type: "tech_book", structure_type: "book" })).toBe("technical")
    expect(readingProfile({ content_type: "tech_article", structure_type: "paper" })).toBe("article")
  })

  it("falls back to article for unknown or missing types", () => {
    expect(readingProfile({})).toBe("article")
    expect(readingProfile({ content_type: "something_new" })).toBe("article")
    expect(readingProfile({ content_type: null, structure_type: null })).toBe("article")
  })
})

describe("profileSpec", () => {
  it("keeps every measure inside the readable range", () => {
    // 50-75 is the research consensus; WCAG caps Latin text at 80.
    for (const profile of ["prose", "article", "paper", "technical", "dialogue", "script", "reference"] as const) {
      const spec = profileSpec(profile)
      expect(spec.measureCh).toBeGreaterThanOrEqual(50)
      expect(spec.measureCh).toBeLessThanOrEqual(80)
    }
  })

  it("sets prose in a serif at the classic 66-character measure", () => {
    const spec = profileSpec("prose")
    expect(spec.measureCh).toBe(66)
    expect(spec.family).toContain("font-serif")
    // A novel with a rule between every chapter reads as a listing.
    expect(spec.dividers).toBe(false)
    expect(spec.headingStyle).toBe("opener")
  })

  it("turns speaker labels on only for dialogue", () => {
    expect(profileSpec("dialogue").speakerTurns).toBe(true)
    for (const profile of ["prose", "article", "paper", "technical", "script", "reference"] as const) {
      expect(profileSpec(profile).speakerTurns).toBe(false)
    }
  })
})

describe("resolveReadingLayout", () => {
  const auto = {
    family: "auto" as const,
    fontScale: 1,
    lineHeight: 1.7,
    measureCh: null,
    tint: "auto" as const,
  }

  it("keeps the profile's choices when everything is left on auto", () => {
    const layout = resolveReadingLayout(profileSpec("prose"), auto)
    expect(layout.family).toContain("font-serif")
    expect(layout.measureCh).toBe(66)
    expect(layout.tinted).toBe(false)
    // Behaviour the profile owns outright still comes through.
    expect(layout.headingStyle).toBe("opener")
    expect(layout.dividers).toBe(false)
  })

  it("lets the reader override the typeface and measure", () => {
    const layout = resolveReadingLayout(profileSpec("prose"), {
      ...auto,
      family: "sans",
      measureCh: 52,
    })
    expect(layout.family).toContain("font-sans")
    expect(layout.family).not.toContain("font-serif")
    expect(layout.measureCh).toBe(52)
  })

  it("overrides headings too, so a serif choice is not undone by the heading rule", () => {
    const layout = resolveReadingLayout(profileSpec("technical"), { ...auto, family: "serif" })
    expect(layout.family).toContain("prose-headings:font-serif")
  })

  it("carries size, spacing and tint through", () => {
    const layout = resolveReadingLayout(profileSpec("article"), {
      ...auto,
      fontScale: 1.25,
      lineHeight: 2,
      tint: "paper",
    })
    expect(layout.fontScale).toBe(1.25)
    expect(layout.lineHeight).toBe(2)
    expect(layout.tinted).toBe(true)
  })
})
