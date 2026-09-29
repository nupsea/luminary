import { forwardRef, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useRef } from "react"
import { acceptCompletion, autocompletion, closeCompletion, completionStatus } from "@codemirror/autocomplete"
import { Compartment, EditorState, Prec } from "@codemirror/state"
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
  dedentMarkdownSpec,
  indentMarkdownSpec,
  insertBlockBreakSpec,
  insertBlockSpec,
  insertInlineSpec,
  moveBlockOrLineSpec,
  replaceSelectionSpec,
  smartBackspaceSpec,
  smartDeleteSpec,
  smartEnterSpec,
  syncDocSpec,
  toggleInlineMarkSpec,
  toggleLinkSpec,
} from "./markdownEditorCommands"
import {
  noteLinkCompletionSource,
  type NoteLinkCompletionConfig,
} from "./noteLinkCompletion"
import { liveMarkdown } from "./liveMarkdown"
import { type ExcalidrawNoteDiagramRef } from "@/lib/noteDiagrams"
import { slashCommandSource, type SlashCommandConfig } from "./slashCommands"
import { toast } from "sonner"
import { logger } from "@/lib/logger"
import { isWithheldImage, readShellClipboardImage } from "@/lib/noteAssets"

export interface MarkdownEditorHandle {
  insertBlock: (markdown: string) => void
  insertInline: (text: string) => void
  replaceSelection: (fn: (selected: string) => string) => void
  getSelection: () => string
  focus: () => void
  scrollDOM: () => HTMLElement | null
  /** Move the cursor to a 0-based line and scroll it to the top (outline nav). */
  scrollToLine: (line: number) => void
  /** Total source lines, for the preview's terminal scroll anchor. */
  lineCount: () => number
  /** 1-based source line at the top of the viewport, fractional within the line. */
  topSourceLine: () => number | null
  /** Scroll (without moving the caret) so `line` sits at the top of the viewport. */
  scrollToSourceLine: (line: number) => void
}

/**
 * Height, in CodeMirror's document coordinate space, of whatever is currently at
 * the top of the scroller.
 *
 * `documentTop` is the document origin in screen coordinates and already accounts
 * for content padding, so subtracting it from the scroller's screen top converts
 * between the two spaces without assuming anything about the theme. Both terms
 * are sub-pixel, which is what keeps the mapping correct under browser zoom —
 * scrollTop/scrollHeight arithmetic rounds and drifts.
 */
function docHeightAtViewportTop(view: EditorView): number {
  return view.scrollDOM.getBoundingClientRect().top - view.documentTop
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
  /** Render markdown as it is written, for a surface with no preview beside it. */
  live?: boolean
  /** Live rendering only: the edit button on a drawn diagram. */
  onEditDiagram?: (diagram: ExcalidrawNoteDiagramRef) => void
  /** Opens the keyboard shortcuts info modal. */
  onOpenShortcuts?: () => void
}

import { usePanelZoomStore } from "@/store/panelZoomStore"

export const DEFAULT_NOTE_FONT_SIZE = 14

// Colors come from the shadcn CSS variables so dark mode flips for free.
const editorTheme = EditorView.theme({
  "&": { height: "100%", fontSize: `var(--note-editor-font-size, ${DEFAULT_NOTE_FONT_SIZE}px)`, backgroundColor: "transparent" },
  ".cm-scroller": {
    fontFamily: "var(--font-sans)",
    lineHeight: "1.65",
    overflow: "auto",
  },
  ".cm-line": {
    lineHeight: "1.65",
  },
  ".cm-content": { minHeight: "100%", padding: "16px 20px", caretColor: "hsl(var(--primary))", cursor: "text" },
  "&.cm-focused": { outline: "none" },
  ".cm-placeholder": { color: "hsl(var(--muted-foreground) / 0.7)" },
  ".cm-cursor": { borderLeftColor: "hsl(var(--primary))", borderLeftWidth: "2px" },
  ".cm-selectionBackground, &.cm-focused .cm-selectionBackground": {
    backgroundColor: "hsl(var(--primary) / 0.35) !important",
  },
  ".cm-content ::selection, .cm-line ::selection, .cm-scroller ::selection": {
    backgroundColor: "hsl(var(--primary) / 0.35) !important",
    color: "#ffffff !important",
  },
  ".cm-selectionMatch": {
    backgroundColor: "hsl(var(--primary) / 0.2) !important",
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
  { tag: t.heading1, fontSize: "1.45em", fontWeight: "700" },
  { tag: t.heading2, fontSize: "1.25em", fontWeight: "600" },
  { tag: t.heading3, fontSize: "1.12em", fontWeight: "600" },
  { tag: t.heading, fontWeight: "600" },
  { tag: t.strong, fontWeight: "700" },
  { tag: t.emphasis, fontStyle: "italic" },
  { tag: t.strikethrough, textDecoration: "line-through" },
  { tag: t.link, color: "hsl(var(--primary))" },
  { tag: t.url, color: "hsl(var(--primary))", textDecoration: "underline" },
  { tag: t.monospace, color: "hsl(var(--primary))", fontFamily: "var(--font-mono)", fontSize: "0.92em" },
  { tag: t.quote, color: "hsl(var(--muted-foreground))", fontStyle: "italic" },
  { tag: t.meta, color: "hsl(var(--muted-foreground))" },
  { tag: t.processingInstruction, color: "hsl(var(--muted-foreground))" },
  { tag: t.labelName, color: "hsl(var(--primary))" },
])

function extractImageFromHtml(html: string): File | null {
  if (!html) return null
  const match = html.match(/<img[^>]+src=["'](data:image\/([a-zA-Z0-9+.-]+);base64,([^"']+))["']/i)
  if (!match) return null
  const [, , subtype, base64] = match
  try {
    const byteCharacters = atob(base64)
    const byteNumbers = new Uint8Array(byteCharacters.length)
    for (let i = 0; i < byteCharacters.length; i++) {
      byteNumbers[i] = byteCharacters.charCodeAt(i)
    }
    const ext = subtype === "jpeg" ? "jpg" : subtype.split("+")[0]
    return new File([byteNumbers], `screenshot.${ext}`, { type: `image/${subtype}` })
  } catch {
    return null
  }
}

function extractImageFile(dataTransfer: DataTransfer | null): File | null {
  if (!dataTransfer) return null

  // 1. Check files list (standard for image files and desktop screenshot paste)
  const files = dataTransfer.files
  if (files && files.length > 0) {
    for (let i = 0; i < files.length; i++) {
      const f = files[i]
      if (f.type.startsWith("image/") || /\.(png|jpe?g|gif|webp|bmp|svg|tiff?)$/i.test(f.name)) {
        return f
      }
    }
  }

  // 2. Check items list
  const items = dataTransfer.items
  if (items && items.length > 0) {
    for (let i = 0; i < items.length; i++) {
      const item = items[i]
      if (item.type.startsWith("image/") || item.kind === "file") {
        const file = item.getAsFile()
        if (
          file &&
          (file.type.startsWith("image/") || /\.(png|jpe?g|gif|webp|bmp|svg|tiff?)$/i.test(file.name))
        ) {
          return file
        }
      }
    }
  }

  // 3. Check HTML for inline base64 images
  const html = dataTransfer.getData("text/html")
  if (html) {
    const file = extractImageFromHtml(html)
    if (file) return file
  }

  return null
}

export const MarkdownCodeEditor = forwardRef<MarkdownEditorHandle, MarkdownCodeEditorProps>(
  function MarkdownCodeEditor(
    { value, onChange, placeholder, autoFocus, className, onScroll, onPasteImage, linkCompletion, slashCommands, live, onEditDiagram, onOpenShortcuts },
    ref,
  ) {
    const hostRef = useRef<HTMLDivElement>(null)
    const viewRef = useRef<EditorView | null>(null)
    const noteEditorZoom = usePanelZoomStore((s) => s.getZoom("note-editor"))
    const fontSizeRoom = useRef(new Compartment()).current
    // The preview pane is a toggle, so live rendering has to be switchable on a
    // view that is already built.
    const liveRoom = useRef(new Compartment()).current
    const latest = useRef({ onChange, onScroll, onPasteImage, linkCompletion, slashCommands, onEditDiagram, onOpenShortcuts })
    latest.current = { onChange, onScroll, onPasteImage, linkCompletion, slashCommands, onEditDiagram, onOpenShortcuts }
    const liveExtension = useCallback(
      () => liveMarkdown({ onEditDiagram: (d) => latest.current.onEditDiagram?.(d) }),
      [],
    )

    useEffect(() => {
      const view = viewRef.current
      if (!view) return
      view.dispatch({
        effects: fontSizeRoom.reconfigure(
          EditorView.theme({
            "&": { fontSize: `${DEFAULT_NOTE_FONT_SIZE * noteEditorZoom}px` },
            ".cm-scroller": { fontSize: `${DEFAULT_NOTE_FONT_SIZE * noteEditorZoom}px` },
          })
        ),
      })
      view.requestMeasure()
    }, [noteEditorZoom, fontSizeRoom])

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
            fontSizeRoom.of(
              EditorView.theme({
                "&": { fontSize: `${DEFAULT_NOTE_FONT_SIZE * noteEditorZoom}px` },
                ".cm-scroller": { fontSize: `${DEFAULT_NOTE_FONT_SIZE * noteEditorZoom}px` },
              })
            ),
            liveRoom.of(live ? liveExtension() : []),
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
            Prec.highest(
              keymap.of([
                {
                  key: "Enter",
                  run: (v) => {
                    const spec = smartEnterSpec(v.state)
                    if (spec) {
                      v.dispatch(spec)
                      return true
                    }
                    return insertNewlineContinueMarkup(v)
                  },
                },
                {
                  key: "Backspace",
                  run: (v) => {
                    const spec = smartBackspaceSpec(v.state)
                    if (spec) {
                      v.dispatch(spec)
                      return true
                    }
                    return deleteMarkupBackward(v)
                  },
                },
                {
                  key: "Delete",
                  run: (v) => {
                    const spec = smartDeleteSpec(v.state)
                    if (spec) {
                      v.dispatch(spec)
                      return true
                    }
                    return false
                  },
                },
                {
                  key: "Tab",
                  run: (v) => {
                    if (completionStatus(v.state) === "active") {
                      return acceptCompletion(v)
                    }
                    const spec = indentMarkdownSpec(v.state)
                    if (spec) {
                      v.dispatch(spec)
                    }
                    return true
                  },
                  preventDefault: true,
                },
                {
                  key: "Shift-Tab",
                  run: (v) => {
                    const spec = dedentMarkdownSpec(v.state)
                    if (spec) {
                      v.dispatch(spec)
                    }
                    return true
                  },
                  preventDefault: true,
                },
              // Line boundary navigation: End / Home (Windows, Linux, and external keyboards on Mac)
              {
                key: "End",
                run: (v) => {
                  const line = v.state.doc.lineAt(v.state.selection.main.head)
                  v.dispatch({ selection: { anchor: line.to }, scrollIntoView: true })
                  return true
                },
                shift: (v) => {
                  const { anchor } = v.state.selection.main
                  const line = v.state.doc.lineAt(v.state.selection.main.head)
                  v.dispatch({ selection: { anchor, head: line.to }, scrollIntoView: true })
                  return true
                },
                preventDefault: true,
              },
              {
                key: "Cmd-ArrowRight",
                mac: "Cmd-ArrowRight",
                run: (v) => {
                  const line = v.state.doc.lineAt(v.state.selection.main.head)
                  v.dispatch({ selection: { anchor: line.to }, scrollIntoView: true })
                  return true
                },
                shift: (v) => {
                  const { anchor } = v.state.selection.main
                  const line = v.state.doc.lineAt(v.state.selection.main.head)
                  v.dispatch({ selection: { anchor, head: line.to }, scrollIntoView: true })
                  return true
                },
                preventDefault: true,
              },
              {
                key: "Home",
                run: (v) => {
                  const head = v.state.selection.main.head
                  const line = v.state.doc.lineAt(head)
                  const firstNonWs = line.text.search(/\S/)
                  const indentPos = firstNonWs === -1 ? line.from : line.from + firstNonWs
                  const target = head === indentPos ? line.from : indentPos
                  v.dispatch({ selection: { anchor: target }, scrollIntoView: true })
                  return true
                },
                shift: (v) => {
                  const { anchor, head } = v.state.selection.main
                  const line = v.state.doc.lineAt(head)
                  const firstNonWs = line.text.search(/\S/)
                  const indentPos = firstNonWs === -1 ? line.from : line.from + firstNonWs
                  const target = head === indentPos ? line.from : indentPos
                  v.dispatch({ selection: { anchor, head: target }, scrollIntoView: true })
                  return true
                },
                preventDefault: true,
              },
              {
                key: "Cmd-ArrowLeft",
                mac: "Cmd-ArrowLeft",
                run: (v) => {
                  const head = v.state.selection.main.head
                  const line = v.state.doc.lineAt(head)
                  const firstNonWs = line.text.search(/\S/)
                  const indentPos = firstNonWs === -1 ? line.from : line.from + firstNonWs
                  const target = head === indentPos ? line.from : indentPos
                  v.dispatch({ selection: { anchor: target }, scrollIntoView: true })
                  return true
                },
                shift: (v) => {
                  const { anchor, head } = v.state.selection.main
                  const line = v.state.doc.lineAt(head)
                  const firstNonWs = line.text.search(/\S/)
                  const indentPos = firstNonWs === -1 ? line.from : line.from + firstNonWs
                  const target = head === indentPos ? line.from : indentPos
                  v.dispatch({ selection: { anchor, head: target }, scrollIntoView: true })
                  return true
                },
                preventDefault: true,
              },
              {
                key: "Alt-ArrowUp",
                mac: "Alt-ArrowUp",
                run: (v) => {
                  const spec = moveBlockOrLineSpec(v.state, -1)
                  if (spec) {
                    v.dispatch(spec)
                    return true
                  }
                  return false
                },
              },
              {
                key: "Alt-ArrowDown",
                mac: "Alt-ArrowDown",
                run: (v) => {
                  const spec = moveBlockOrLineSpec(v.state, 1)
                  if (spec) {
                    v.dispatch(spec)
                    return true
                  }
                  return false
                },
              },
              {
                key: "Mod-Enter",
                run: (v) => {
                  const spec = insertBlockBreakSpec(v.state)
                  if (spec) {
                    v.dispatch(spec)
                    return true
                  }
                  return false
                },
              },
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
              {
                key: "Mod-k",
                run: (v) => {
                  v.dispatch(toggleLinkSpec(v.state))
                  return true
                },
              },
              {
                key: "Mod-Shift-s",
                run: (v) => {
                  v.dispatch(toggleInlineMarkSpec(v.state, "~~"))
                  return true
                },
              },
              {
                key: "Mod-Shift-x",
                run: (v) => {
                  v.dispatch(toggleInlineMarkSpec(v.state, "~~"))
                  return true
                },
              },
              {
                key: "Mod-`",
                run: (v) => {
                  v.dispatch(toggleInlineMarkSpec(v.state, "`"))
                  return true
                },
              },
              {
                key: "Mod-/",
                run: () => {
                  if (latest.current.onOpenShortcuts) {
                    latest.current.onOpenShortcuts()
                    return true
                  }
                  return false
                },
              },
              ...defaultKeymap,
              ...historyKeymap,
            ])),
            EditorView.updateListener.of((update) => {
              if (update.docChanged) latest.current.onChange(update.state.doc.toString())
            }),
            EditorView.domEventHandlers({
              scroll: () => {
                latest.current.onScroll?.()
              },
              paste: (event, v) => {
                const handler = latest.current.onPasteImage
                if (!handler) return false

                const file = extractImageFile(event.clipboardData)
                if (!file && !isWithheldImage(event.clipboardData)) return false
                event.preventDefault()
                ;(file ? Promise.resolve(file) : readShellClipboardImage())
                  .then((image) => (image ? handler(image) : Promise.reject(new Error("no image"))))
                  .then((md) => {
                    v.dispatch(insertBlockSpec(v.state, md))
                  })
                  .catch((err) => {
                    toast.error("Failed to paste image")
                    logger.warn("Failed to paste image", err)
                  })
                return true
              },
              drop: (event, v) => {
                const handler = latest.current.onPasteImage
                if (!handler) return false

                const file = extractImageFile(event.dataTransfer)
                if (file) {
                  event.preventDefault()
                  handler(file)
                    .then((md) => {
                      v.dispatch(insertBlockSpec(v.state, md))
                    })
                    .catch((err) => {
                      toast.error("Failed to upload dropped image")
                      logger.warn("Failed to upload dropped image", err)
                    })
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

    useEffect(() => {
      viewRef.current?.dispatch({
        effects: liveRoom.reconfigure(live ? liveExtension() : []),
      })
      // liveExtension reads its callback through `latest`, so it never goes stale.
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [live])

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
        lineCount: () => viewRef.current?.state.doc.lines ?? 0,
        topSourceLine: () => {
          const v = viewRef.current
          if (!v) return null
          const height = Math.max(0, docHeightAtViewportTop(v))
          const block = v.lineBlockAtHeight(height)
          const line = v.state.doc.lineAt(block.from).number
          if (block.height <= 0) return line
          // A wrapped line is one block, so the fraction locates the visual row
          // within it -- without this, sync quantises to whole source lines.
          const within = Math.min(1, Math.max(0, (height - block.top) / block.height))
          return line + within
        },
        scrollToSourceLine: (line) => {
          const v = viewRef.current
          if (!v) return
          const clamped = Math.min(Math.max(line, 1), v.state.doc.lines)
          const whole = Math.floor(clamped)
          const block = v.lineBlockAt(v.state.doc.line(whole).from)
          const target = block.top + (clamped - whole) * block.height
          v.scrollDOM.scrollTop += target - docHeightAtViewportTop(v)
        },
      }),
      [],
    )

    return (
      <div
        ref={hostRef}
        data-zoom-panel="note-editor"
        style={{ "--note-editor-font-size": `${DEFAULT_NOTE_FONT_SIZE * noteEditorZoom}px` } as React.CSSProperties}
        className={className}
      />
    )
  },
)
