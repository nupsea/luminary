import { useRef, useState } from "react"
import { Check, FileText, LayoutGrid, Loader2, Tag, Wand2 } from "lucide-react"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { TagAutocomplete } from "@/components/TagAutocomplete"
import { NoteDiagramDialog } from "@/components/NoteDiagramDialog"
import { MermaidCheatSheet } from "@/components/notes/MermaidCheatSheet"
import { MermaidQuickInsert } from "@/components/notes/MermaidQuickInsert"
import {
  NoteCollectionsField,
  type CollectionOption,
} from "@/components/notes/NoteCollectionsField"
import {
  NoteSourceDocsField,
  type SourceDocOption,
} from "@/components/notes/NoteSourceDocsField"
import {
  createImagePasteHandler,
  insertAtTextareaCursor,
} from "@/lib/noteEditorUtils"
import {
  replaceExcalidrawDiagram,
  type ExcalidrawNoteDiagramRef,
} from "@/lib/noteDiagrams"

export type NoteEditorLayout = "splitter" | "tabs"

export interface NoteEditorProps {
  content: string
  onContentChange: (next: string) => void
  tags: string[]
  onTagsChange: (next: string[]) => void
  selectedDocIds: string[]
  onSelectedDocIdsChange: (next: string[]) => void
  checkedCollectionIds: Set<string>
  onCollectionToggle: (collectionId: string, checked: boolean) => void
  documents: SourceDocOption[]
  collections: CollectionOption[]
  layout?: NoteEditorLayout
  isNew?: boolean
  lockedCollectionId?: string | null
  collectionsLoading?: boolean
  showCollections?: boolean
  showSourceDocs?: boolean
  showImageSize?: boolean
  suggestedTags?: string[]
  suggestionsBusy?: boolean
  onSuggestTags?: () => void
  onAddSuggestedTag?: (tag: string) => void
  onDismissSuggestions?: () => void
  imageVariant?: (path: string) => string
  textareaClassName?: string
}

const IMAGE_SIZES = ["small", "medium", "large"] as const

export function NoteEditor({
  content,
  onContentChange,
  tags,
  onTagsChange,
  selectedDocIds,
  onSelectedDocIdsChange,
  checkedCollectionIds,
  onCollectionToggle,
  documents,
  collections,
  layout = "splitter",
  isNew = false,
  lockedCollectionId = null,
  collectionsLoading,
  showCollections = true,
  showSourceDocs = true,
  showImageSize = true,
  suggestedTags = [],
  suggestionsBusy = false,
  onSuggestTags,
  onAddSuggestedTag,
  onDismissSuggestions,
  imageVariant = (path) => `![Pasted Image|medium](${path})`,
  textareaClassName,
}: NoteEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const previewRef = useRef<HTMLDivElement>(null)
  const splitContainerRef = useRef<HTMLDivElement>(null)
  const syncingRef = useRef<"write" | "preview" | null>(null)

  const [leftPct, setLeftPct] = useState(50)
  const [dragging, setDragging] = useState(false)
  const [activeTab, setActiveTab] = useState<"write" | "preview">("write")
  const [diagramOpen, setDiagramOpen] = useState(false)
  const [editingDiagramRef, setEditingDiagramRef] = useState<ExcalidrawNoteDiagramRef | null>(null)

  function handleDiagramSaved(markdown: string) {
    if (editingDiagramRef) {
      onContentChange(replaceExcalidrawDiagram(content, editingDiagramRef, markdown))
      setEditingDiagramRef(null)
      return
    }
    insertAtTextareaCursor(textareaRef.current, content, onContentChange, markdown)
  }

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

  function insertImageSizeMarkdown(size: (typeof IMAGE_SIZES)[number]) {
    const ta = textareaRef.current
    const start = ta?.selectionStart ?? content.length
    const end = ta?.selectionEnd ?? content.length
    const selectedText = content.substring(start, end)
    let next = ""
    const match = selectedText.match(/!\[([^\]]*?)\]\((.*?)\)/)
    if (match) {
      const altText = match[1]
      const url = match[2]
      const altClean = altText.split("|")[0].trim() || "Image"
      next = `![${altClean}|${size}](${url})`
    } else {
      next = `![Image|${size}](url)`
    }
    onContentChange(content.substring(0, start) + next + content.substring(end))
    setTimeout(() => {
      const newPos = start + next.length
      textareaRef.current?.setSelectionRange(newPos, newPos)
      textareaRef.current?.focus()
    }, 0)
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

  function openDiagramEditor(ref: ExcalidrawNoteDiagramRef) {
    setEditingDiagramRef(ref)
    setDiagramOpen(true)
  }

  const writePane = (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <div className="flex flex-wrap items-center gap-1.5">
        {showImageSize && (
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] text-muted-foreground">Image spec:</span>
            {IMAGE_SIZES.map((size) => (
              <button
                key={size}
                type="button"
                onClick={() => insertImageSizeMarkdown(size)}
                className="rounded border border-border bg-background px-1.5 py-0.5 text-[10px] font-medium hover:bg-accent text-foreground capitalize"
              >
                {size}
              </button>
            ))}
          </div>
        )}
        <div className="flex flex-wrap items-center gap-1.5">
          <MermaidQuickInsert
            onInsert={(markdown) =>
              insertAtTextareaCursor(textareaRef.current, content, onContentChange, markdown)
            }
            onDraw={() => {
              setEditingDiagramRef(null)
              setDiagramOpen(true)
            }}
          />
        </div>
      </div>
      <MermaidCheatSheet />
      <textarea
        ref={textareaRef}
        value={content}
        onChange={(e) => onContentChange(e.target.value)}
        onScroll={layout === "splitter" ? () => syncScroll("write") : undefined}
        onPaste={createImagePasteHandler(
          // eslint-disable-next-line react-hooks/refs
          () => textareaRef.current,
          () => content,
          onContentChange,
          imageVariant,
        )}
        placeholder="Write your note in Markdown..."
        className={
          textareaClassName ??
          "w-full flex-1 resize-none overflow-auto rounded border-none bg-background px-2 py-2 font-mono text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-0"
        }
      />
    </div>
  )

  const previewPane = (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      {layout === "splitter" && (
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            Preview
          </span>
        </div>
      )}
      <div
        ref={previewRef}
        onScroll={layout === "splitter" ? () => syncScroll("preview") : undefined}
        className="prose-sm flex-1 overflow-auto px-2 py-2"
      >
        {content.trim() ? (
          <MarkdownRenderer onEditExcalidrawDiagram={openDiagramEditor}>
            {content}
          </MarkdownRenderer>
        ) : (
          <p className="text-muted-foreground italic text-sm">Preview will appear here...</p>
        )}
      </div>
    </div>
  )

  return (
    <>
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      {layout === "splitter" ? (
        <div
          ref={splitContainerRef}
          className={`flex flex-1 min-h-0 items-stretch overflow-hidden ${dragging ? "select-none cursor-col-resize" : ""}`}
        >
          <div
            className="flex flex-col gap-2 min-w-0 min-h-0 h-full"
            style={{ width: `${leftPct}%` }}
          >
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                Editor
              </span>
            </div>
            {writePane}
          </div>
          <div
            onMouseDown={handleSplitterMouseDown}
            className="mx-3 w-1 shrink-0 cursor-col-resize self-stretch rounded bg-border hover:bg-primary/40 transition-colors"
            title="Drag to resize"
          />
          <div
            className="flex flex-col gap-2 min-w-0 min-h-0 h-full"
            style={{ width: `${100 - leftPct}%` }}
          >
            {previewPane}
          </div>
        </div>
      ) : (
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
      )}

      <div className="shrink-0 space-y-4 border-t border-border pt-4">
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-muted-foreground">
              <Tag size={12} />
              <span className="text-[10px] font-bold uppercase tracking-wider">Tags</span>
            </div>
            {onSuggestTags && !isNew && (
              <button
                onClick={onSuggestTags}
                disabled={suggestionsBusy}
                className="flex items-center gap-1 text-[10px] text-primary hover:underline disabled:opacity-50"
              >
                {suggestionsBusy ? (
                  <Loader2 size={10} className="animate-spin" />
                ) : (
                  <Wand2 size={10} />
                )}
                Suggest tags
              </button>
            )}
          </div>
          <div className="flex flex-col gap-3">
            <TagAutocomplete tags={tags} onChange={onTagsChange} />
            {suggestedTags.length > 0 && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[10px] font-medium text-muted-foreground">Suggestions:</span>
                {suggestedTags.map((tag) => (
                  <button
                    key={tag}
                    onClick={() => onAddSuggestedTag?.(tag)}
                    className="flex items-center gap-1 rounded-full border border-dashed border-primary/30 bg-primary/5 px-2 py-0.5 text-[11px] text-primary hover:bg-primary/10 transition-colors"
                  >
                    <Check size={9} />
                    {tag}
                  </button>
                ))}
                {onDismissSuggestions && (
                  <button
                    onClick={onDismissSuggestions}
                    className="text-[10px] text-muted-foreground hover:underline"
                  >
                    Dismiss
                  </button>
                )}
              </div>
            )}
          </div>
        </div>

        {(showCollections || showSourceDocs) && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {showCollections && (
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2 text-muted-foreground">
                  <LayoutGrid size={12} />
                  <span className="text-[10px] font-bold uppercase tracking-wider">Collections</span>
                </div>
                <NoteCollectionsField
                  collections={collections}
                  checkedIds={checkedCollectionIds}
                  onToggle={onCollectionToggle}
                  loading={collectionsLoading}
                  lockedCollectionId={lockedCollectionId}
                />
              </div>
            )}
            {showSourceDocs && (
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2 text-muted-foreground">
                  <FileText size={12} />
                  <span className="text-[10px] font-bold uppercase tracking-wider">Source Documents</span>
                </div>
                <NoteSourceDocsField
                  documents={documents}
                  selectedIds={selectedDocIds}
                  onChange={onSelectedDocIdsChange}
                  emptyMessage="No source documents available"
                />
              </div>
            )}
          </div>
        )}
      </div>
    </div>
    <NoteDiagramDialog
      open={diagramOpen}
      onOpenChange={setDiagramOpen}
      scenePath={editingDiagramRef?.scenePath}
      onSaved={handleDiagramSaved}
    />
    </>
  )
}
