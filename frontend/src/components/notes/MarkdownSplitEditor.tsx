import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react"
import {
  MarkdownCodeEditor,
  type MarkdownEditorHandle,
} from "@/components/notes/MarkdownCodeEditor"
import { type NoteLinkCompletionConfig } from "@/components/notes/noteLinkCompletion"
import { type SlashCommandConfig } from "@/components/notes/slashCommands"
import {
  lineToOffset,
  normalizeAnchors,
  offsetToLine,
  type SourceAnchor,
} from "@/components/notes/scrollSync"
import { SOURCE_LINE_ATTR } from "@/lib/rehypeSourceLine"

export type MarkdownSplitLayout = "splitter" | "tabs" | "editor"

export interface MarkdownSplitEditorProps {
  content: string
  onContentChange: (next: string) => void
  preview: ReactNode
  layout?: MarkdownSplitLayout
  editorRef?: RefObject<MarkdownEditorHandle | null>
  onPasteImage?: (file: File) => Promise<string>
  linkCompletion?: NoteLinkCompletionConfig
  slashCommands?: SlashCommandConfig
  placeholder?: string
  autoFocus?: boolean
  editorLabel?: string
  previewLabel?: string
  editorClassName?: string
  previewClassName?: string
}

const DEFAULT_EDITOR_CLASS =
  "min-h-0 w-full flex-1 overflow-hidden rounded border-none bg-background text-foreground"

const DEFAULT_PREVIEW_CLASS = "prose-sm flex-1 overflow-auto px-2 py-2"

// Treat a pane as scrolled to its end within this many pixels. Not zero: at
// fractional zoom levels scrollTop is sub-pixel while scrollHeight/clientHeight
// are integers, so a pane at its true limit never reports an exact match.
const AT_END_PX = 4

export function MarkdownSplitEditor({
  content,
  onContentChange,
  preview,
  layout = "splitter",
  editorRef: externalEditorRef,
  onPasteImage,
  linkCompletion,
  slashCommands,
  placeholder = "Write your note in Markdown...",
  autoFocus,
  editorLabel = "Editor",
  previewLabel = "Preview",
  editorClassName,
  previewClassName,
}: MarkdownSplitEditorProps) {
  const internalEditorRef = useRef<MarkdownEditorHandle | null>(null)
  const editorRef = externalEditorRef ?? internalEditorRef
  const previewRef = useRef<HTMLDivElement>(null)
  const splitContainerRef = useRef<HTMLDivElement>(null)
  const syncingRef = useRef<"write" | "preview" | null>(null)
  const anchorsRef = useRef<{ signature: string; anchors: SourceAnchor[] }>({
    signature: "",
    anchors: [],
  })

  const [leftPct, setLeftPct] = useState(50)
  const [dragging, setDragging] = useState(false)
  const [activeTab, setActiveTab] = useState<"write" | "preview">("write")

  /**
   * Measure where each rendered block starts, relative to the preview's scroll
   * origin. Offsets come from getBoundingClientRect rather than offsetTop so they
   * stay sub-pixel accurate at any browser zoom, and so they are unaffected by
   * whatever positioned ancestors the surrounding layout introduces.
   */
  function measurePreviewAnchors(previewEl: HTMLElement, totalLines: number): SourceAnchor[] {
    const origin = previewEl.getBoundingClientRect().top - previewEl.scrollTop
    const raw: SourceAnchor[] = []
    for (const el of previewEl.querySelectorAll<HTMLElement>(`[${SOURCE_LINE_ATTR}]`)) {
      raw.push({
        line: Number(el.getAttribute(SOURCE_LINE_ATTR)),
        top: el.getBoundingClientRect().top - origin,
      })
    }
    return normalizeAnchors(raw, totalLines, previewEl.scrollHeight - previewEl.clientHeight)
  }

  /**
   * Anchors are reused across scroll events — measuring every block on each one
   * would mean hundreds of layout reads per frame on a long note. The signature
   * covers everything that can move a block: an edit, a reflow (zoom, resize,
   * splitter drag), and content settling after paint such as an image finishing
   * loading, which changes scrollHeight without resizing the pane itself.
   */
  function previewAnchors(previewEl: HTMLElement, totalLines: number): SourceAnchor[] {
    const signature = `${totalLines}:${previewEl.scrollHeight}:${previewEl.clientHeight}:${previewEl.clientWidth}`
    if (anchorsRef.current.signature !== signature) {
      anchorsRef.current = {
        signature,
        anchors: measurePreviewAnchors(previewEl, totalLines),
      }
    }
    return anchorsRef.current.anchors
  }

  function syncScroll(source: "write" | "preview") {
    if (syncingRef.current && syncingRef.current !== source) return
    const editor = editorRef.current
    const writeEl = editor?.scrollDOM() ?? null
    const previewEl = previewRef.current
    const src = source === "write" ? writeEl : previewEl
    const dst = source === "write" ? previewEl : writeEl
    if (!src || !dst || !editor || !previewEl) return
    const dstMax = dst.scrollHeight - dst.clientHeight
    if (dstMax <= 0) return

    const anchors = previewAnchors(previewEl, editor.lineCount())
    syncingRef.current = source

    const srcAtEnd = src.scrollHeight - src.clientHeight - src.scrollTop <= AT_END_PX

    if (anchors.length >= 2) {
      // Line-anchored: convert through the shared source-line axis, so each
      // region uses its own pixels-per-line rather than a document-wide average.
      if (source === "write") {
        // Anchoring aligns the pane *tops*. At the end of the document that is
        // not enough: if the tail renders taller than it does in the editor, the
        // line just typed still falls below the preview's fold. Showing the end
        // of one pane must show the end of the other.
        const line = srcAtEnd ? null : editor.topSourceLine()
        previewEl.scrollTop = line == null ? dstMax : lineToOffset(line, anchors)
      } else {
        editor.scrollToSourceLine(
          srcAtEnd ? editor.lineCount() : offsetToLine(previewEl.scrollTop, anchors),
        )
      }
    } else {
      // No anchors: a preview that is not a tracked MarkdownRenderer (the blog
      // dialogs wrap theirs in extra chrome). Proportional is all we can do.
      const srcMax = src.scrollHeight - src.clientHeight
      if (srcMax > 0) {
        dst.scrollTop = srcAtEnd ? dstMax : (src.scrollTop / srcMax) * dstMax
      }
    }

    requestAnimationFrame(() => {
      syncingRef.current = null
    })
  }

  // Typing at the bottom of the editor does not always fire a scroll event (the
  // caret is already visible), and when it does the preview has not yet re-rendered
  // the new text, so its anchors are stale. Either way the preview is left behind
  // and freshly-typed content scrolls out of view. Re-sync after the preview
  // re-renders on a content change.
  useEffect(() => {
    if (layout !== "splitter") return
    // Second frame catches preview height changes that land after the first
    // paint (web fonts, images, KaTeX) and would leave the sync short.
    let id2 = 0
    const id = requestAnimationFrame(() => {
      syncScroll("write")
      id2 = requestAnimationFrame(() => syncScroll("write"))
    })
    return () => {
      cancelAnimationFrame(id)
      cancelAnimationFrame(id2)
    }
    // syncScroll reads live DOM through refs; re-run only when content/layout change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content, layout])

  // Anchor offsets are measurements, so anything that reflows either pane
  // invalidates them: browser zoom (which rewraps the serif preview and the
  // monospace editor by different amounts), window resize, and splitter drags.
  // None of those change `content`, so the effect above never sees them.
  useEffect(() => {
    if (layout !== "splitter") return
    const previewEl = previewRef.current
    const writeEl = editorRef.current?.scrollDOM() ?? null
    if (!previewEl) return
    let frame = 0
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => syncScroll("write"))
    })
    observer.observe(previewEl)
    if (writeEl) observer.observe(writeEl)
    return () => {
      cancelAnimationFrame(frame)
      observer.disconnect()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layout])

  function handleSplitterMouseDown(e: React.MouseEvent) {
    if (layout !== "splitter") return
    e.preventDefault()
    setDragging(true)
    function onMove(ev: MouseEvent) {
      const el = splitContainerRef.current
      if (!el) return
      const rect = el.getBoundingClientRect()
      const pct = ((ev.clientX - rect.left) / rect.width) * 100
      setLeftPct(Math.min(85, Math.max(15, pct)))
    }
    function onUp() {
      setDragging(false)
      window.removeEventListener("mousemove", onMove)
      window.removeEventListener("mouseup", onUp)
    }
    window.addEventListener("mousemove", onMove)
    window.addEventListener("mouseup", onUp)
  }

  const writePane = (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <MarkdownCodeEditor
        ref={editorRef}
        value={content}
        onChange={onContentChange}
        onScroll={layout === "splitter" ? () => syncScroll("write") : undefined}
        onPasteImage={onPasteImage}
        linkCompletion={linkCompletion}
        slashCommands={slashCommands}
        placeholder={placeholder}
        autoFocus={autoFocus}
        className={editorClassName ?? DEFAULT_EDITOR_CLASS}
      />
    </div>
  )

  const previewPane = (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      {layout === "splitter" && (
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            {previewLabel}
          </span>
        </div>
      )}
      <div
        ref={previewRef}
        onScroll={layout === "splitter" ? () => syncScroll("preview") : undefined}
        className={previewClassName ?? DEFAULT_PREVIEW_CLASS}
      >
        {preview}
      </div>
    </div>
  )

  if (layout === "editor") {
    return writePane
  }

  if (layout === "splitter") {
    return (
      <div
        ref={splitContainerRef}
        className={`flex flex-1 min-h-0 items-stretch overflow-hidden ${dragging ? "select-none cursor-col-resize" : ""}`}
      >
        <div className="flex flex-col gap-2 min-w-0 min-h-0 h-full" style={{ width: `${leftPct}%` }}>
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              {editorLabel}
            </span>
          </div>
          {writePane}
        </div>
        <div
          onMouseDown={handleSplitterMouseDown}
          className="mx-3 w-1 shrink-0 cursor-col-resize self-stretch rounded bg-border hover:bg-primary/40 transition-colors"
          title="Drag to resize"
        />
        <div className="flex flex-col gap-2 min-w-0 min-h-0 h-full" style={{ width: `${100 - leftPct}%` }}>
          {previewPane}
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <div className="flex shrink-0 items-center gap-1 border-b border-border">
        <button
          type="button"
          onClick={() => setActiveTab("write")}
          className={`px-3 py-1.5 text-xs font-medium ${
            activeTab === "write"
              ? "border-b-2 border-primary text-foreground"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Write
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("preview")}
          className={`px-3 py-1.5 text-xs font-medium ${
            activeTab === "preview"
              ? "border-b-2 border-primary text-foreground"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Preview
        </button>
      </div>
      {activeTab === "write" ? writePane : previewPane}
    </div>
  )
}
