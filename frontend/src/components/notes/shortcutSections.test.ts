import { describe, expect, it } from "vitest"
import { EditorSelection, EditorState, type TransactionSpec } from "@codemirror/state"
import { markdown, markdownLanguage } from "@codemirror/lang-markdown"
import { keymap } from "@codemirror/view"
import { noteEditorKeymaps } from "./MarkdownCodeEditor"
import { liveMarkdown } from "./liveMarkdown"
import { noteShortcutSections } from "./shortcutSections"

function boundKeys(): Set<string> {
  const state = EditorState.create({
    extensions: [markdown({ base: markdownLanguage }), ...noteEditorKeymaps({ current: {} }), liveMarkdown()],
  })
  const keys = new Set<string>()
  for (const b of state.facet(keymap).flat()) {
    if (b.key) keys.add(b.key)
    if (b.mac) keys.add(b.mac)
  }
  return keys
}

describe("note editor shortcuts list", () => {
  it.each([true, false])("binds every key it names (mac=%s)", (isMac) => {
    const bound = boundKeys()
    for (const surface of ["page", "composer"] as const) {
      const unbound = noteShortcutSections(isMac, surface)
        .flatMap((s) => s.items)
        .filter((item) => item.binding && !bound.has(item.binding))
        .map((item) => `${item.description}: ${item.binding}`)
      expect(unbound).toEqual([])
    }
  })

  it("does not offer the reading-view toggle where there is none", () => {
    const describes = (surface: "page" | "composer") =>
      noteShortcutSections(true, surface).flatMap((s) => s.items.map((i) => i.description))
    expect(describes("page")).toContain("Toggle reading / editing view")
    expect(describes("composer")).not.toContain("Toggle reading / editing view")
  })

  it("wraps the selection in inline math", () => {
    const binding = noteEditorKeymaps({ current: {} })
    const state = EditorState.create({
      doc: "let x = y",
      selection: EditorSelection.single(4, 9),
      extensions: [markdown({ base: markdownLanguage }), ...binding],
    })
    const run = state.facet(keymap).flat().find((b) => b.key === "Mod-Shift-e")!.run!
    let next = state
    run({ state, dispatch: (spec: TransactionSpec) => (next = state.update(spec).state) } as never)
    expect(next.doc.toString()).toBe("let $x = y$")
  })
})
