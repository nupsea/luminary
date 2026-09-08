/**
 * The reader opens nothing over the document.
 *
 * Every workflow that used to be a modal -- the note composer, the
 * conversation, the explanation, the flashcard generator and the Feynman
 * session -- is now a face of the docked panel. A browser check can only see
 * the modals that a particular run happens to open; this one sees every file.
 *
 * The document's own delete confirmation is a popover, not a dialog, and is
 * what the exception below would otherwise have to carve out.
 */
import { readFileSync, readdirSync } from "node:fs"
import { join } from "node:path"

import { describe, expect, it } from "vitest"

const READER_DIR = join(import.meta.dirname, ".")

function readerSources(): { name: string; source: string }[] {
  return readdirSync(READER_DIR)
    .filter((f) => (f.endsWith(".tsx") || f.endsWith(".ts")) && !f.includes(".test."))
    .map((name) => ({ name, source: readFileSync(join(READER_DIR, name), "utf8") }))
}

describe("the reader's surfaces", () => {
  it("imports no dialog or sheet primitive", () => {
    const offenders = readerSources()
      .filter(({ source }) => /from "@\/components\/ui\/(dialog|sheet|drawer|alert-dialog)"/.test(source))
      .map(({ name }) => name)
    expect(offenders).toEqual([])
  })

  it("names no component a dialog or a sheet", () => {
    const offenders = readerSources()
      .filter(({ name }) => /(Dialog|Sheet)\.tsx$/.test(name))
      .map(({ name }) => name)
    expect(offenders).toEqual([])
  })

  it("mounts every docked face beside the document", () => {
    const reader = readFileSync(join(READER_DIR, "DocumentReader.tsx"), "utf8")
    for (const face of [
      "ChatConversation",
      "NoteComposer",
      "ExplanationPanel",
      "DocumentFlashcardPanel",
      "FeynmanPanel",
    ]) {
      expect(reader, `${face} is not mounted in the reader`).toContain(`<${face}`)
    }
  })
})
