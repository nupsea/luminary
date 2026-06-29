import { useRef, useState } from "react"
import { Check, ChevronUp, FileText, LayoutGrid, Loader2, Tag, Wand2, Wrench } from "lucide-react"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { TagAutocomplete } from "@/components/TagAutocomplete"
import { NoteDiagramDialog } from "@/components/NoteDiagramDialog"
import { MarkdownSplitEditor } from "@/components/notes/MarkdownSplitEditor"
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
  showMeta?: boolean
  showToolbar?: boolean
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
  showMeta = true,
  showToolbar = true,
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

  const [diagramOpen, setDiagramOpen] = useState(false)
  const [editingDiagramRef, setEditingDiagramRef] = useState<ExcalidrawNoteDiagramRef | null>(null)
  const [toolbarOpen, setToolbarOpen] = useState(true)

  function handleDiagramSaved(markdown: string) {
    if (editingDiagramRef) {
      onContentChange(replaceExcalidrawDiagram(content, editingDiagramRef, markdown))
      setEditingDiagramRef(null)
      return
    }
    insertAtTextareaCursor(textareaRef.current, content, onContentChange, markdown)
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

  function openDiagramEditor(ref: ExcalidrawNoteDiagramRef) {
    setEditingDiagramRef(ref)
    setDiagramOpen(true)
  }

  const editorToolbar = showToolbar ? (
    <>
      <div className="flex items-center justify-between gap-2">
        {toolbarOpen ? (
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
        ) : (
          <span />
        )}
        <button
          type="button"
          onClick={() => setToolbarOpen((v) => !v)}
          className="shrink-0 rounded border border-border bg-background p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          title={toolbarOpen ? "Hide formatting tools" : "Show formatting tools"}
          aria-label={toolbarOpen ? "Hide formatting tools" : "Show formatting tools"}
        >
          {toolbarOpen ? <ChevronUp size={12} /> : <Wrench size={12} />}
        </button>
      </div>
      {toolbarOpen && <MermaidCheatSheet />}
    </>
  ) : null

  return (
    <>
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <MarkdownSplitEditor
        layout={layout}
        content={content}
        onContentChange={onContentChange}
        textareaRef={textareaRef}
        editorToolbar={editorToolbar}
        placeholder="Write your note in Markdown..."
        onPaste={createImagePasteHandler(
          () => textareaRef.current,
          () => content,
          onContentChange,
          imageVariant,
        )}
        textareaClassName={textareaClassName}
        preview={
          content.trim() ? (
            <MarkdownRenderer serif onEditExcalidrawDiagram={openDiagramEditor}>
              {content}
            </MarkdownRenderer>
          ) : (
            <p className="text-muted-foreground italic text-sm">Preview will appear here...</p>
          )
        }
      />

      {showMeta && (
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
      )}
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
