import { describe, expect, it } from "vitest"

import { describeContents, suggestedLibraryName } from "./libraryTransfer"

describe("suggestedLibraryName", () => {
  it("offers the exported library's own name", () => {
    expect(suggestedLibraryName("luminary-work-20261118-101500.tar.gz")).toBe("work")
  })

  it("offers nothing for the default library, whose name is taken on every machine", () => {
    expect(suggestedLibraryName("luminary-default-20261118-101500.tar.gz")).toBe("")
  })

  it("offers nothing for a renamed or unrelated file", () => {
    expect(suggestedLibraryName("my backup.tar.gz")).toBe("")
    expect(suggestedLibraryName("luminary-work-20261118-101500 (1).tar.gz")).toBe("")
  })
})

describe("describeContents", () => {
  it("counts each kind, singular and plural", () => {
    expect(describeContents({ documents: 1, flashcards: 2300, notes: 0 })).toBe(
      `1 document, ${(2300).toLocaleString()} cards, 0 notes`,
    )
  })
})
