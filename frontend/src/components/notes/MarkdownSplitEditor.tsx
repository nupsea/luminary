import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react"
import {
  MarkdownCodeEditor,
  type MarkdownEditorHandle,
} from "@/components/notes/MarkdownCodeEditor"
import { type NoteLinkCompletionConfig } from "@/components/notes/noteLinkCompletion"
import { type SlashCommandConfig } from "@/components/notes/slashCommands"

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

  const [leftPct, setLeftPct] = useState(50)
  const [dragging, setDragging] = useState(false)
  const [activeTab, setActiveTab] = useState<"write" | "preview">("write")

  function syncScroll(source: "write" | "preview") {
    if (syncingRef.current && syncingRef.current !== source) return
    const writeEl = editorRef.current?.scrollDOM() ?? null
    const previewEl = previewRef.current
    const src = source === "write" ? writeEl : previewEl
    const dst = source === "write" ? previewEl : writeEl
    if (!src || !dst) return
    const srcMax = src.scrollHeight - src.clientHeight
    const dstMax = dst.scrollHeight - dst.clientHeight
    if (srcMax <= 0 || dstMax <= 0) return
    syncingRef.current = source
    // Proportional mapping is approximate (monospace editor vs serif preview), so
    // near the end it can leave the last lines cut off. When the source is at or
    // near its bottom — the type-at-end case — pin the destination to its true
    // bottom so freshly typed text is always visible in the preview.
    const nearBottom = srcMax - src.scrollTop <= 24
    dst.scrollTop = nearBottom ? dstMax : (src.scrollTop / srcMax) * dstMax
    requestAnimationFrame(() => {
      syncingRef.current = null
    })
  }

  // Typing at the bottom of the editor does not always fire a scroll event (the
  // caret is already visible), and when it does the preview has not yet re-rendered
  // the new text, so its height is stale. Either way the preview is left behind and
  // freshly-typed content scrolls out of view. Re-sync after the preview re-renders
  // on a content change so it follows the editor's scroll position.
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
