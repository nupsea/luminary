import { describe, expect, it } from "vitest"

import { createPracticeReturn } from "./practiceReturn"

describe("createPracticeReturn", () => {
  it("returns to the spot before the first revealed answer, not a later source", () => {
    const back = createPracticeReturn()
    back.hold({ tab: "read", sectionId: "ch-3" })
    back.hold({ tab: "read", sectionId: "ch-2" })
    back.hold({ tab: "read", sectionId: "ch-2b" })
    expect(back.release()).toEqual({ tab: "read", sectionId: "ch-3" })
  })

  it("returns once per run, and the next run holds its own spot", () => {
    const back = createPracticeReturn()
    back.hold({ tab: "pdfview", sectionId: null })
    back.release()
    expect(back.release()).toBeNull()
    back.hold({ tab: "read", sectionId: "ch-5" })
    expect(back.release()).toEqual({ tab: "read", sectionId: "ch-5" })
  })

  it("has nowhere to return when no answer was revealed", () => {
    expect(createPracticeReturn().release()).toBeNull()
  })
})
