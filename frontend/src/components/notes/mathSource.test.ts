import { describe, expect, it } from "vitest"
import { EditorState } from "@codemirror/state"
import { markdown, markdownLanguage } from "@codemirror/lang-markdown"
import { ensureSyntaxTree } from "@codemirror/language"
import { mathRanges } from "./mathSource"

const doc = [
  "Prose with $a + b$ and `code $x$`.",
  "",
  "```sh",
  "echo $HOME $PATH",
  "$$",
  "not math",
  "$$",
  "```",
  "",
  "| col | $t$ |",
  "| --- | --- |",
  "",
  "$$",
  "e = mc^2",
  "$$",
].join("\n")

function ranges(text: string) {
  const state = EditorState.create({ doc: text, extensions: [markdown({ base: markdownLanguage })] })
  ensureSyntaxTree(state, state.doc.length, 5000)
  const { display, inline } = mathRanges(state)
  const slice = (r: { from: number; to: number }) => text.slice(r.from, r.to)
  return { display: display.map(slice), inline: inline.map(slice) }
}

describe("mathRanges", () => {
  it("finds math in prose and display blocks, never inside code or tables", () => {
    expect(ranges(doc)).toEqual({ display: ["$$\ne = mc^2\n$$"], inline: ["$a + b$"] })
  })
})
