import { useRef, useState, type ReactNode, type RefObject } from "react"

export type MarkdownSplitLayout = "splitter" | "tabs"

export interface MarkdownSplitEditorProps {
  content: string
  onContentChange: (next: string) => void
  preview: ReactNode
  layout?: MarkdownSplitLayout
  textareaRef?: RefObject<HTMLTextAreaElement | null>
  onPaste?: React.ClipboardEventHandler<HTMLTextAreaElement>
  editorToolbar?: ReactNode
  placeholder?: string
  editorLabel?: string
  previewLabel?: string
  textareaClassName?: string
  previewClassName?: string
}

const DEFAULT_TEXTAREA_CLASS =
  "w-full flex-1 resize-none overflow-auto rounded border-none bg-background px-2 py-2 font-mono text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-0"

const DEFAULT_PREVIEW_CLASS = "prose-sm flex-1 overflow-auto px-2 py-2"

export function MarkdownSplitEditor({
  content,
  onContentChange,
  preview,
  layout = "splitter",
  textareaRef: externalTextareaRef,
  onPaste,
  editorToolbar,
  placeholder = "Write your note in Markdown...",
  editorLabel = "Editor",
  previewLabel = "Preview",
  textareaClassName,
  previewClassName,
}: MarkdownSplitEditorProps) {
  const internalTextareaRef = useRef<HTMLTextAreaElement>(null)
  const textareaRef = externalTextareaRef ?? internalTextareaRef
  const previewRef = useRef<HTMLDivElement>(null)
  const splitContainerRef = useRef<HTMLDivElement>(null)
  const syncingRef = useRef<"write" | "preview" | null>(null)

  const [leftPct, setLeftPct] = useState(50)
  const [dragging, setDragging] = useState(false)
  const [activeTab, setActiveTab] = useState<"write" | "preview">("write")

  function syncScroll(source: "write" | "preview") {
    if (syncingRef.current && syncingRef.current !== source) return
    const src = source === "write" ? textareaRef.current : previewRef.current
    const dst = source === "write" ? previewRef.current : textareaRef.current
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
      <textarea
        ref={textareaRef}
        value={content}
        onChange={(e) => onContentChange(e.target.value)}
        onScroll={layout === "splitter" ? () => syncScroll("write") : undefined}
        onPaste={onPaste}
        placeholder={placeholder}
        className={textareaClassName ?? DEFAULT_TEXTAREA_CLASS}
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
