import { useRef, useState, type ReactNode, type RefObject } from "react"
import {
  MarkdownCodeEditor,
  type MarkdownEditorHandle,
} from "@/components/notes/MarkdownCodeEditor"
import { type NoteLinkCompletionConfig } from "@/components/notes/noteLinkCompletion"

export type MarkdownSplitLayout = "splitter" | "tabs" | "editor"

export interface MarkdownSplitEditorProps {
  content: string
  onContentChange: (next: string) => void
  preview: ReactNode
  layout?: MarkdownSplitLayout
  editorRef?: RefObject<MarkdownEditorHandle | null>
  onPasteImage?: (file: File) => Promise<string>
  linkCompletion?: NoteLinkCompletionConfig
  editorToolbar?: ReactNode
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
  editorToolbar,
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
    dst.scrollTop = (src.scrollTop / srcMax) * dstMax
    requestAnimationFrame(() => {
      syncingRef.current = null
    })
  }

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
      {editorToolbar}
      <MarkdownCodeEditor
        ref={editorRef}
        value={content}
        onChange={onContentChange}
        onScroll={layout === "splitter" ? () => syncScroll("write") : undefined}
        onPasteImage={onPasteImage}
        linkCompletion={linkCompletion}
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
