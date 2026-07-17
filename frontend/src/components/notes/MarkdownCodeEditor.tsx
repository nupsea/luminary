import { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useRef } from "react"
import { autocompletion, closeCompletion, completionStatus } from "@codemirror/autocomplete"
import { EditorState } from "@codemirror/state"
import {
  EditorView,
  drawSelection,
  dropCursor,
  keymap,
  placeholder as cmPlaceholder,
} from "@codemirror/view"
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands"
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language"
import {
  deleteMarkupBackward,
  insertNewlineContinueMarkup,
  markdown,
  markdownLanguage,
} from "@codemirror/lang-markdown"
import { languages } from "@codemirror/language-data"
import { tags as t } from "@lezer/highlight"
import {
  insertBlockSpec,
  insertInlineSpec,
  replaceSelectionSpec,
  syncDocSpec,
  toggleInlineMarkSpec,
} from "./markdownEditorCommands"
import {
  noteLinkCompletionSource,
  type NoteLinkCompletionConfig,
} from "./noteLinkCompletion"
import { slashCommandSource, type SlashCommandConfig } from "./slashCommands"

export interface MarkdownEditorHandle {
  insertBlock: (markdown: string) => void
  insertInline: (text: string) => void
  replaceSelection: (fn: (selected: string) => string) => void
  getSelection: () => string
  focus: () => void
  scrollDOM: () => HTMLElement | null
  /** Move the cursor to a 0-based line and scroll it to the top (outline nav). */
  scrollToLine: (line: number) => void
}

export interface MarkdownCodeEditorProps {
  value: string
  onChange: (next: string) => void
  placeholder?: string
  autoFocus?: boolean
  className?: string
  onScroll?: () => void
  /** Upload a pasted image and return the markdown to insert at the cursor. */
  onPasteImage?: (file: File) => Promise<string>
  /** Enables the [[ note-link autocomplete. */
  linkCompletion?: NoteLinkCompletionConfig
  /** Enables the / block-insert menu at line start. */
  slashCommands?: SlashCommandConfig
}

// Colors come from the shadcn CSS variables so dark mode flips for free.
const editorTheme = EditorView.theme({
  "&": { height: "100%", fontSize: "13.5px", backgroundColor: "transparent" },
  ".cm-scroller": {
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    lineHeight: "1.65",
    overflow: "auto",
  },
  ".cm-content": { padding: "8px 6px", caretColor: "hsl(var(--foreground))" },
  "&.cm-focused": { outline: "none" },
  ".cm-placeholder": { color: "hsl(var(--muted-foreground))" },
  ".cm-cursor": { borderLeftColor: "hsl(var(--foreground))" },
  ".cm-selectionBackground, &.cm-focused .cm-selectionBackground": {
    backgroundColor: "hsl(var(--primary) / 0.18)",
  },
  // Completion popup restyled to the app's popover look (the CM default is a
  // stark blue box that clashes with the rest of the UI).
  ".cm-tooltip": {
    backgroundColor: "hsl(var(--popover))",
    color: "hsl(var(--popover-foreground))",
    border: "1px solid hsl(var(--border))",
    borderRadius: "8px",
    boxShadow: "0 8px 24px rgb(0 0 0 / 0.12)",
    overflow: "hidden",
  },
  ".cm-tooltip.cm-tooltip-autocomplete > ul": {
    fontFamily: "var(--font-sans)",
    maxHeight: "280px",
    minWidth: "220px",
  },
  ".cm-tooltip-autocomplete > ul > li": {
    padding: "5px 10px",
    lineHeight: "1.4",
    color: "hsl(var(--popover-foreground))",
  },
  ".cm-tooltip-autocomplete > ul > li[aria-selected]": {
    backgroundColor: "hsl(var(--accent))",
    color: "hsl(var(--accent-foreground))",
  },
  ".cm-completionLabel": { fontSize: "12.5px" },
  ".cm-completionMatchedText": {
    textDecoration: "none",
    color: "hsl(var(--primary))",
    fontWeight: "600",
  },
  ".cm-completionDetail": {
    marginLeft: "10px",
    fontSize: "10.5px",
    fontStyle: "normal",
    color: "hsl(var(--muted-foreground))",
  },
  ".cm-completionSection": {
    padding: "7px 10px 3px",
    fontSize: "9.5px",
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: "0.06em",
    color: "hsl(var(--muted-foreground))",
  },
  ".cm-tooltip.cm-completionInfo": {
    padding: "8px 10px",
    maxWidth: "340px",
    fontFamily: "var(--font-mono)",
    fontSize: "10.5px",
    whiteSpace: "pre-wrap",
  },
})

const mdHighlight = HighlightStyle.define([
  { tag: t.heading1, fontSize: "1.3em", fontWeight: "700" },
  { tag: t.heading2, fontSize: "1.15em", fontWeight: "700" },
  { tag: t.heading3, fontSize: "1.05em", fontWeight: "600" },
  { tag: t.heading, fontWeight: "600" },
  { tag: t.strong, fontWeight: "700" },
  { tag: t.emphasis, fontStyle: "italic" },
  { tag: t.strikethrough, textDecoration: "line-through" },
  { tag: t.link, color: "hsl(var(--primary))" },
  { tag: t.url, color: "hsl(var(--primary))", textDecoration: "underline" },
  { tag: t.monospace, color: "hsl(var(--primary))" },
  { tag: t.quote, color: "hsl(var(--muted-foreground))", fontStyle: "italic" },
  { tag: t.meta, color: "hsl(var(--muted-foreground))" },
  { tag: t.processingInstruction, color: "hsl(var(--muted-foreground))" },
  { tag: t.labelName, color: "hsl(var(--primary))" },
])

export const MarkdownCodeEditor = forwardRef<MarkdownEditorHandle, MarkdownCodeEditorProps>(
  function MarkdownCodeEditor(
    { value, onChange, placeholder, autoFocus, className, onScroll, onPasteImage, linkCompletion, slashCommands },
    ref,
  ) {
    const hostRef = useRef<HTMLDivElement>(null)
    const viewRef = useRef<EditorView | null>(null)
    const latest = useRef({ onChange, onScroll, onPasteImage, linkCompletion, slashCommands })
    latest.current = { onChange, onScroll, onPasteImage, linkCompletion, slashCommands }

    useEffect(() => {
      const view = new EditorView({
        state: EditorState.create({
          doc: value,
          extensions: [
            history(),
            drawSelection(),
            dropCursor(),
            EditorView.lineWrapping,
            markdown({ base: markdownLanguage, codeLanguages: languages }),
            syntaxHighlighting(mdHighlight),
            editorTheme,
            cmPlaceholder(placeholder ?? ""),
            autocompletion({
              override: [
                slashCommandSource(() => latest.current.slashCommands),
                noteLinkCompletionSource(() => latest.current.linkCompletion),
              ],
              icons: false,
              // Default 100ms feels laggy; the sources are local/near-local.
              activateOnTypingDelay: 25,
              // Our filter:false sources re-open the result per keystroke,
              // which resets the interaction guard; at the default 75ms a
              // prompt ArrowDown/Enter gets rejected and falls through to
              // cursor motion, killing the popup.
              interactionDelay: 30,
            }),
            keymap.of([
              { key: "Enter", run: insertNewlineContinueMarkup },
              { key: "Backspace", run: deleteMarkupBackward },
              {
                key: "Mod-b",
                run: (v) => {
                  v.dispatch(toggleInlineMarkSpec(v.state, "**"))
                  return true
                },
              },
              {
                key: "Mod-i",
                run: (v) => {
                  v.dispatch(toggleInlineMarkSpec(v.state, "*"))
                  return true
                },
              },
              ...defaultKeymap,
              ...historyKeymap,
            ]),
            EditorView.updateListener.of((update) => {
              if (update.docChanged) latest.current.onChange(update.state.doc.toString())
            }),
            EditorView.domEventHandlers({
              scroll: () => {
                latest.current.onScroll?.()
              },
              paste: (event, v) => {
                const items = event.clipboardData?.items
                const handler = latest.current.onPasteImage
                if (!items || !handler) return false
                for (let i = 0; i < items.length; i++) {
                  if (!items[i].type.startsWith("image")) continue
                  const file = items[i].getAsFile()
                  if (!file) continue
                  event.preventDefault()
                  handler(file)
                    .then((md) => {
                      v.dispatch(insertInlineSpec(v.state, md))
                    })
                    .catch(() => {})
                  return true
                }
                return false
              },
            }),
          ],
        }),
        parent: hostRef.current!,
      })
      viewRef.current = view
      if (autoFocus) view.focus()
      // Radix dialogs grab Escape at document capture -- before CM's own
      // handler -- so an open completion popup would either not close or take
      // the whole sheet with it. Window capture runs first; consume the key
      // and close just the popup.
      function onEscapeCapture(e: KeyboardEvent) {
        if (e.key !== "Escape") return
        if (completionStatus(view.state) === null) return
        e.preventDefault()
        e.stopPropagation()
        closeCompletion(view)
      }
      window.addEventListener("keydown", onEscapeCapture, { capture: true })
      return () => {
        window.removeEventListener("keydown", onEscapeCapture, { capture: true })
        view.destroy()
        viewRef.current = null
      }
      // The view is created once; value/placeholder changes flow through the
      // sync effect below and the latest ref.
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    useLayoutEffect(() => {
      const view = viewRef.current
      if (!view) return
      const spec = syncDocSpec(view.state, value)
      if (spec) view.dispatch(spec)
    }, [value])

    useImperativeHandle(
      ref,
      () => ({
        insertBlock: (md) => {
          const v = viewRef.current
          if (!v) return
          v.dispatch(insertBlockSpec(v.state, md))
          v.focus()
        },
        insertInline: (text) => {
          const v = viewRef.current
          if (!v) return
          v.dispatch(insertInlineSpec(v.state, text))
          v.focus()
        },
        replaceSelection: (fn) => {
          const v = viewRef.current
          if (!v) return
          v.dispatch(replaceSelectionSpec(v.state, fn))
          v.focus()
        },
        getSelection: () => {
          const v = viewRef.current
          if (!v) return ""
          const { from, to } = v.state.selection.main
          return v.state.sliceDoc(from, to)
        },
        focus: () => viewRef.current?.focus(),
        scrollDOM: () => viewRef.current?.scrollDOM ?? null,
        scrollToLine: (line) => {
          const v = viewRef.current
          if (!v) return
          const docLine = v.state.doc.line(Math.min(line + 1, v.state.doc.lines))
          v.dispatch({
            selection: { anchor: docLine.from },
            effects: EditorView.scrollIntoView(docLine.from, { y: "start", yMargin: 8 }),
          })
          v.focus()
        },
      }),
      [],
    )

    return <div ref={hostRef} className={className} />
  },
)
