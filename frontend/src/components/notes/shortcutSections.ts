/**
 * The note editor's shortcuts as the user reads them. `binding` is the
 * CodeMirror key an item claims, so a test can hold the list to the keymap;
 * window-level keys (save, reading view) carry none.
 */

export type ShortcutSurface = "page" | "composer"

export interface ShortcutItem {
  keys: string[]
  description: string
  detail?: string
  binding?: string
}

export interface ShortcutSection {
  title: string
  items: ShortcutItem[]
}

export function noteShortcutSections(isMac: boolean, surface: ShortcutSurface): ShortcutSection[] {
  const MOD = isMac ? "⌘" : "Ctrl"
  const ALT = isMac ? "⌥" : "Alt"
  const SHIFT = isMac ? "⇧" : "Shift"

  return [
    {
      title: "Lists & Indentation",
      items: [
        {
          keys: ["Tab"],
          description: "Indent list item or selected lines",
          detail: "In tables: next cell",
          binding: "Tab",
        },
        {
          keys: [SHIFT, "Tab"],
          description: "Outdent list item or lines",
          detail: "In tables: previous cell",
          binding: "Shift-Tab",
        },
        {
          keys: ["Enter"],
          description: "Continue list item or quote",
          detail: "Numbers count up (1. → 2.); Enter on an empty item ends the list",
          binding: "Enter",
        },
        {
          keys: [MOD, SHIFT, "C"],
          description: "Toggle task checkbox",
          binding: "Mod-Shift-c",
        },
      ],
    },
    {
      title: "Formatting & Links",
      items: [
        { keys: [MOD, "B"], description: "Bold", binding: "Mod-b" },
        { keys: [MOD, "I"], description: "Italic", binding: "Mod-i" },
        {
          keys: [MOD, SHIFT, "S"],
          description: "Strikethrough",
          detail: `${MOD} + ${SHIFT} + X also works`,
          binding: "Mod-Shift-s",
        },
        { keys: [MOD, "`"], description: "Inline code", binding: "Mod-`" },
        {
          keys: [MOD, SHIFT, "E"],
          description: "Inline math",
          detail: "Wraps the selection in $…$; renders with KaTeX once the caret leaves the line",
          binding: "Mod-Shift-e",
        },
        {
          keys: [MOD, "K"],
          description: "Link to a note",
          detail: "Opens note search for the selection; where notes cannot be linked, wraps it as [text](url)",
          binding: "Mod-k",
        },
      ],
    },
    {
      title: "Navigation & Line Editing",
      items: [
        {
          keys: isMac ? ["⌘", "→"] : ["End"],
          description: "Jump to end of line",
          detail: isMac ? "End works too on a full keyboard" : undefined,
          binding: isMac ? "Cmd-ArrowRight" : "End",
        },
        {
          keys: isMac ? ["⌘", "←"] : ["Home"],
          description: "Jump to start of line / indentation",
          detail: "Press again to toggle between the first character and column 0",
          binding: isMac ? "Cmd-ArrowLeft" : "Home",
        },
        {
          keys: isMac ? [SHIFT, "⌘", "→ / ←"] : [SHIFT, "End / Home"],
          description: "Select to end / start of line",
        },
        { keys: [ALT, "↑ / ↓"], description: "Move line or block up or down", binding: "Alt-ArrowUp" },
        { keys: [SHIFT, ALT, "↑ / ↓"], description: "Duplicate line up or down", binding: "Shift-Alt-ArrowUp" },
        {
          keys: [MOD, "Enter"],
          description: "New paragraph below the current block",
          detail: "Leaves a table, code or math block without touching its delimiters",
          binding: "Mod-Enter",
        },
        {
          keys: ["→ / ←", "↑ / ↓"],
          description: "Step into a rendered block",
          detail: "Tables, code, math and diagrams give their source back",
          binding: "ArrowDown",
        },
      ],
    },
    {
      title: "Notes & Smart Triggers",
      items: [
        {
          keys: ["/"],
          description: "Block menu",
          detail: "At the start of a line: headings, lists, tables, code, math block, images, diagrams",
        },
        { keys: ["[["], description: "Link to another note", detail: "Type to search notes" },
        ...(surface === "page"
          ? [{ keys: [MOD, "E"], description: "Toggle reading / editing view" }]
          : []),
        { keys: [MOD, "S"], description: "Save now", detail: "Notes also autosave as you type" },
        { keys: [MOD, "/"], description: "Show or hide these shortcuts", binding: "Mod-/" },
      ],
    },
  ]
}
