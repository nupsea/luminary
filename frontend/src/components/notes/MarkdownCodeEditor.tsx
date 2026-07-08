import { forwardRef, useEffect, useImperativeHandle, useRef } from "react"
import { autocompletion } from "@codemirror/autocomplete"
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
  toggleInlineMarkSpec,
} from "./markdownEditorCommands"
import {
  noteLinkCompletionSource,
  type NoteLinkCompletionConfig,
} from "./noteLinkCompletion"

export interface MarkdownEditorHandle {
  insertBlock: (markdown: string) => void
  insertInline: (text: string) => void
  replaceSelection: (fn: (selected: string) => string) => void
  getSelection: () => string
  focus: () => void
  scrollDOM: () => HTMLElement | null
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
    { value, onChange, placeholder, autoFocus, className, onScroll, onPasteImage, linkCompletion },
    ref,
  ) {
    const hostRef = useRef<HTMLDivElement>(null)
    const viewRef = useRef<EditorView | null>(null)
    const latest = useRef({ onChange, onScroll, onPasteImage, linkCompletion })
    latest.current = { onChange, onScroll, onPasteImage, linkCompletion }

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
              override: [noteLinkCompletionSource(() => latest.current.linkCompletion)],
              icons: false,
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
      return () => {
        view.destroy()
        viewRef.current = null
      }
      // The view is created once; value/placeholder changes flow through the
      // sync effect below and the latest ref.
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    useEffect(() => {
      const view = viewRef.current
      if (!view) return
      const current = view.state.doc.toString()
      if (value !== current) {
        view.dispatch({ changes: { from: 0, to: current.length, insert: value } })
      }
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
      }),
      [],
    )

    return <div ref={hostRef} className={className} />
  },
)
