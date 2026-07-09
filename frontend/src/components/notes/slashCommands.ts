import {
  startCompletion,
  type Completion,
  type CompletionContext,
  type CompletionResult,
} from "@codemirror/autocomplete"
import type { EditorView } from "@codemirror/view"
import { MERMAID_TEMPLATES } from "@/lib/mermaidNotes"

export interface SlashCommandConfig {
  /** Opens the Excalidraw dialog. Absent = the Draw item is hidden. */
  onDrawDiagram?: () => void
}

interface SlashItem {
  label: string
  detail: string
  section: string
  keywords?: string[]
  needsDraw?: boolean
  /** Shown in the completion info panel (e.g. mermaid template source). */
  info?: string
  run: (view: EditorView, from: number, to: number, config: SlashCommandConfig) => void
}

const replaceWith =
  (insert: string, cursorOffset?: number) =>
  (view: EditorView, from: number, to: number) => {
    view.dispatch({
      changes: { from, to, insert },
      selection: { anchor: from + (cursorOffset ?? insert.length) },
      scrollIntoView: true,
    })
  }

const TABLE_TEMPLATE = "| Column | Column |\n| --- | --- |\n|  |  |\n"

const SLASH_ITEMS: SlashItem[] = [
  { label: "Heading 1", detail: "#", section: "Blocks", keywords: ["h1", "title"], run: replaceWith("# ") },
  { label: "Heading 2", detail: "##", section: "Blocks", keywords: ["h2"], run: replaceWith("## ") },
  { label: "Heading 3", detail: "###", section: "Blocks", keywords: ["h3"], run: replaceWith("### ") },
  { label: "Bullet list", detail: "-", section: "Lists", keywords: ["ul", "list"], run: replaceWith("- ") },
  { label: "Numbered list", detail: "1.", section: "Lists", keywords: ["ol", "ordered"], run: replaceWith("1. ") },
  { label: "Task list", detail: "- [ ]", section: "Lists", keywords: ["todo", "checkbox"], run: replaceWith("- [ ] ") },
  { label: "Quote", detail: ">", section: "Blocks", keywords: ["blockquote"], run: replaceWith("> ") },
  { label: "Divider", detail: "---", section: "Blocks", keywords: ["hr", "rule"], run: replaceWith("---\n") },
  { label: "Table", detail: "3x2", section: "Blocks", keywords: ["grid"], run: replaceWith(TABLE_TEMPLATE, 2) },
  {
    label: "Code block",
    detail: "```",
    section: "Blocks",
    keywords: ["fence", "snippet"],
    run: replaceWith("```\n\n```\n", 4),
  },
  {
    label: "Math block",
    detail: "$$",
    section: "Blocks",
    keywords: ["latex", "katex", "equation"],
    run: replaceWith("$$\n\n$$\n", 3),
  },
  {
    label: "Image",
    detail: "![...]",
    section: "Insert",
    keywords: ["picture", "img"],
    run: replaceWith("![Image|medium](url)", 20),
  },
  {
    label: "Link to note",
    detail: "[[",
    section: "Insert",
    keywords: ["wiki", "backlink", "connect"],
    run: (view, from, to) => {
      view.dispatch({
        changes: { from, to, insert: "[[" },
        selection: { anchor: from + 2 },
      })
      startCompletion(view)
    },
  },
  ...MERMAID_TEMPLATES.map(
    (template): SlashItem => ({
      label: `Mermaid: ${template.label}`,
      detail: "diagram",
      section: "Diagrams",
      keywords: ["chart", "graph", template.label.toLowerCase()],
      info: template.markdown,
      run: replaceWith(`${template.markdown}\n`),
    }),
  ),
  {
    label: "Draw diagram",
    detail: "Excalidraw",
    section: "Diagrams",
    keywords: ["sketch", "excalidraw", "draw"],
    needsDraw: true,
    run: (view, from, to, config) => {
      view.dispatch({ changes: { from, to, insert: "" } })
      config.onDrawDiagram?.()
    },
  },
]

export function slashCommandSource(getConfig: () => SlashCommandConfig | undefined) {
  return (ctx: CompletionContext): CompletionResult | null => {
    const config = getConfig()
    if (!config) return null
    const match = ctx.matchBefore(/\/[\w-]*$/)
    if (!match) return null
    // Line-start only, so typing "and/or" mid-sentence never opens the menu.
    if (match.from !== ctx.state.doc.lineAt(ctx.pos).from) return null
    const query = match.text.slice(1).toLowerCase()
    const options: Completion[] = SLASH_ITEMS.filter(
      (item) =>
        (!item.needsDraw || config.onDrawDiagram) &&
        (query === "" ||
          item.label.toLowerCase().includes(query) ||
          item.keywords?.some((k) => k.includes(query))),
    ).map((item) => ({
      label: item.label,
      detail: item.detail,
      section: item.section,
      info: item.info,
      apply: (view: EditorView, _completion: unknown, from: number, to: number) =>
        item.run(view, from, to, config),
    }))
    if (options.length === 0) return null
    return { from: match.from, options, filter: false }
  }
}
